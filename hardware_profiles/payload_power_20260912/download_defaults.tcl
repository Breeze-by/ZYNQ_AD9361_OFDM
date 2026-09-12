# Load each PC's newly exported hardware and its own rebuilt ELF. No RAM patches.
# Args: sender|receiver. Does not program Flash/SD.
if {$argc != 1 || [lindex $argv 0] ni {sender receiver}} {error "Expected sender|receiver"}
set role [lindex $argv 0]
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
set image [file join $repo System_wrapper_hw_platform_0]
set elf [file join $repo AD9361_test2 Debug AD9361_test2.elf]
if {$role eq "sender"} {
    set sdk D:/vivado2018/SDK/2018.3
    set expected_gain 36; set expected_att 16000
} else {
    set sdk D:/Xilinx/SDK/2018.3
    set expected_gain 66; set expected_att 25000
}
foreach p [list $elf [file join $image System_wrapper.bit] [file join $image system.hdf] [file join $image ps7_init.tcl]] {if {![file isfile $p]} {error "Missing $p"}}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing ELF symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
proc step {s} {puts "STAGE18_LOAD_STEP $s"; flush stdout}
step connect
connect -url tcp:127.0.0.1:3121
for {set n 0} {$n < 10} {incr n} {
    if {[llength [targets -target-properties -filter {name =~ "APU"}]]} {break}
    after 1000
}
targets -set -filter {name =~ "APU"}
step reset_system
rst -system
after 2000
targets -set -filter {name =~ "xc7z020"}
step program_fpga
fpga -file [file join $image System_wrapper.bit]
targets -set -filter {name =~ "ARM*#0"}
source [file join $image ps7_init.tcl]
step ps7_init
ps7_init
foreach {a expected} {0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600} {
    if {[u32 $a] != $expected} {error "Unexpected FCLK at $a"}
}
ps7_post_config
step download_elf
dow $elf
if {[u32 [symbol gain]] != $expected_gain || [u32 [symbol txatt]] != $expected_att} {error "Wrong compiled role; CPU left stopped"}
if {[u32 [symbol sample_rate]] != 40000000} {error "Wrong sample rate"}
step run_without_ram_patch
con
after 12000
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $image system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0x40000050 0xA7170002 0x4000207c 0xA7170002
    0x40000008 0xA704205D 0x40002014 0xA7048304
    0x40002004 0x101 0x40002008 0x00300000 0x4000200c 63
    0x40002010 0x0FFFE001 0x40002048 0x1FFFF
} {
    set actual [u32 $a]
    if {$actual != $expected} {error [format "Startup mismatch at %08X: got %08X expected %08X" $a $actual $expected]}
    puts [format "STAGE18_RUNTIME_REG %08X=%08X" $a $actual]
}
if {[u32 [symbol gain]] != $expected_gain || [u32 [symbol txatt]] != $expected_att} {error "Runtime role changed"}
puts "STAGE18_LOADED role=$role gain=[u32 [symbol gain]] txatt=[u32 [symbol txatt]] guard=32 shift=4 no_ram_patch=1"
disconnect
