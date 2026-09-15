# Sender candidate only, traffic stopped. ADI API readback, no reinitialization.
if {$argc != 2} {error "Expected trial-root and attenuation in milli-dB"}
lassign $argv audit requested
if {![string is integer -strict $requested] || $requested < 14000 || $requested > 20000 || $requested % 250 != 0} {error "Outside 14..20dB / 0.25dB sweep"}
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
set bin D:/vivado2018/SDK/2018.3/gnu/aarch32/nt/gcc-arm-none-eabi/bin
set elf [file join $audit attenuation candidate.elf]
set table [exec [file join $bin arm-none-eabi-nm.exe] -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a]&0xffffffff}]}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $repo System_wrapper_hw_platform_0 system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
set start [symbol file_ber_control_poll]
set dis [exec [file join $bin arm-none-eabi-objdump.exe] -d --start-address=$start --stop-address=[expr {$start+32}] $elf]
set n 0
foreach line [split $dis \n] {
    if {[regexp {^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s} $line unused at word]} {
        if {[u32 [scan $at %x]] != ([scan $word %x]&0xffffffff)} {error "Wrong running candidate; no writes"}
        incr n
    }
}
if {$n != 8 || [u32 0x40000050] != 0xa7170002 || [u32 0x40000004] != 127} {error "Unexpected mailbox/hardware"}
set a [symbol file_ber_result]
if {[u32 $a] != 0xa7250001} {error "Mailbox signature mismatch"}
set count [u32 [expr {$a+4}]]
mwr 0x40000004 [expr {0xa725007f | (($requested/250)<<8)}]
after 1000
if {[u32 0x40000004] != 127 || [u32 [expr {$a+4}]] != $count+1 || [u32 [expr {$a+8}]] != $requested || [u32 [expr {$a+12}]] != 0 || [u32 [expr {$a+16}]] != $requested || [u32 [expr {$a+20}]] != $requested} {error "ADI attenuation API readback failed; stop sending"}
puts "FILE_BER_ATT_OK both_channels_mdb=$requested count=[u32 [expr {$a+4}]]"
disconnect
