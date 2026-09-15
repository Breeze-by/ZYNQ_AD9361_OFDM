# Sender only, stopped traffic. Processor ELF reload; never programs FPGA/Flash.
# Usage: xsct load_tx.tcl <trial-root> candidate|restore
if {$argc != 2} {error "Expected audit directory and candidate|restore"}
lassign $argv audit mode
if {$mode ni {candidate restore}} {error "Invalid mode"}
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
set bin D:/vivado2018/SDK/2018.3/gnu/aarch32/nt/gcc-arm-none-eabi/bin
set original [file join $audit before AD9361_test2.elf]
set candidate [file join $audit attenuation candidate.elf]
set current [expr {$mode eq "candidate" ? $original : $candidate}]
set elf [expr {$mode eq "candidate" ? $candidate : $original}]
foreach f [list $current $elf] {if {![file isfile $f]} {error "Missing $f"}}
proc u32 {a} {return [expr {[mrd -value $a]&0xffffffff}]}
proc symbol {elf name} {
    global bin
    set table [exec [file join $bin arm-none-eabi-nm.exe] -n $elf]
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing $name"}
    return [scan $hex %x]
}
proc prefix {elf} {
    global bin
    set a [symbol $elf net_snr_request]
    set dis [exec [file join $bin arm-none-eabi-objdump.exe] -d --start-address=$a --stop-address=[expr {$a+32}] $elf]
    set n 0
    foreach line [split $dis \n] {
        if {[regexp {^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s} $line unused at word]} {
            if {[u32 [scan $at %x]] != ([scan $word %x]&0xffffffff)} {error "Unexpected running code at $at"}
            incr n
        }
    }
    if {$n != 8} {error "Incomplete code prefix"}
    puts "ELF_PREFIX_VERIFIED $elf words=$n"
}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $repo System_wrapper_hw_platform_0 system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a v} {0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600 0x40000050 0xa7170002 0x4000207c 0xa7170002} {
    if {[u32 $a] != $v} {error "Wrong hardware at $a"}
}
prefix $current
targets -set -filter {name =~ "ARM*#0"}
stop
rst -processor
after 1000
dow $elf
con
after 12000
targets -set -filter {name =~ "APU"}
prefix $elf
foreach {a v} {0x40000008 0xa704205d 0x40002014 0xa7048304 0x40002008 0x00300000 0x4000200c 63} {
    if {[u32 $a] != $v} {error "Startup configuration differs at $a"}
}
foreach {name expected} {sample_rate 40000000 gain 36 txatt 16000} {
    if {[u32 [symbol $elf $name]] != $expected} {error "Wrong role $name"}
}
puts "FILE_BER_TX_LOADED mode=$mode sample_rate=40000000 gain=36 txatt=16000"
disconnect
