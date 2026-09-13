# Receiver only. This reinitializes AD9361: compare runs within each startup.
if {$argc!=1 || [lindex $argv 0] ni {observe quiet restore}} {error "Expected observe|quiet|restore"}
set mode [lindex $argv 0]
set d [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set backup [file join $d stage21-before-trace]
set image $backup
if {$mode in {observe quiet}} {set image [file join $d stage21-observe-a]}
set elf [file join $backup AD9361_test2.elf]
if {$mode eq "quiet"} {set elf [file join $d stage21-quiet candidate.elf]}
foreach f [list $elf [file join $image System_wrapper.bit] [file join $backup system.hdf] [file join $backup ps7_init.tcl]] {if {![file isfile $f]} {error "Missing $f"}}
set table [exec D:/Xilinx/SDK/2018.3/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a]&0xffffffff}]}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
rst -system
after 2000
targets -set -filter {name =~ "xc7z020"}
fpga -file [file join $image System_wrapper.bit]
targets -set -filter {name =~ "ARM*#0"}
source [file join $backup ps7_init.tcl]
ps7_init
ps7_post_config
dow $elf
if {[u32 [symbol gain]]!=66 || [u32 [symbol txatt]]!=25000 || [u32 [symbol sample_rate]]!=40000000} {error "Wrong receiver ELF; CPU stopped"}
con
after 12000
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $backup system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xa7170002 0x4000207c 0xa7170002
    0x40000008 0xa704205d 0x40002014 0xa7048304
    0x40002004 0x101 0x40002008 0x00300000 0x4000200c 63
    0x4000007c 0 0x40002074 0
} {if {[u32 $a]!=$expected} {error "Unexpected startup register $a"}}
mwr 0x40002008 0x002c0000
if {[u32 0x40002008]!=0x002c0000} {error "DC44 restoration failed"}
puts "STAGE21_LOAD_OK mode=$mode gain=66 atten_mdb=25000 power_code=4 dc=44"
disconnect
