# Temporary JTAG load / restore. Never writes Flash, SD, source, or SDK platform.
# Each PC MUST use its own stage17-before-power backup ELF.
if {$argc != 2} {error "Expected sender|receiver and candidate|restore"}
lassign $argv role mode
if {$role ni {sender receiver} || $mode ni {candidate restore}} {error "Invalid selection"}
proc stage {name} {
    puts "STAGE17_LOAD_STEP [clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S}] $name"
    flush stdout
}
stage "inputs role=$role mode=$mode"
set diag [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set backup [file join $diag stage17-before-power]
set elf [file join $backup AD9361_test2.elf]
if {$mode eq "candidate"} {set image [file join $diag stage17-image]} else {set image $backup}
set bit [file join $image System_wrapper.bit]
set init [file join $image ps7_init.tcl]
set hdf [file join $image system.hdf]
foreach p [list $elf $bit $init $hdf] {if {![file isfile $p]} {error "Missing input $p"}}
if {$role eq "sender"} {
    set sdk D:/vivado2018/SDK/2018.3
    set expected_gain 36
    set expected_att 22000
} else {
    set sdk D:/Xilinx/SDK/2018.3
    set expected_gain 66
    set expected_att 25000
}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing ELF symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
set gain_addr [symbol gain]
set att_addr [symbol txatt]
stage connect
connect -url tcp:127.0.0.1:3121
for {set attempt 0} {$attempt < 10} {incr attempt} {
    if {[llength [targets -target-properties -filter {name =~ "APU"}]] > 0} {break}
    after 1000
}
targets -set -filter {name =~ "APU"}
stage reset_system
rst -system
after 2000
targets -set -filter {name =~ "xc7z020"}
stage program_original_or_candidate_fpga
fpga -file $bit
stage fpga_program_complete
targets -set -filter {name =~ "ARM*#0"}
source $init
stage ps7_init
ps7_init
stage verify_clocks
foreach {address expected} {0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600} {
    if {[u32 $address] != $expected} {error "Unexpected clock divider $address; CPU left stopped"}
}
ps7_post_config
stage download_role_elf
dow $elf
if {[u32 $gain_addr] != $expected_gain || [u32 $att_addr] != $expected_att} {error "Wrong role ELF; CPU left stopped"}
stage run_role_elf
con
after 12000
stage verify_runtime
targets -set -filter {name =~ "APU"}
loadhw -hw $hdf -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {address expected} {0x40002004 0x101 0x40002008 0x00300000 0x4000200c 63 0x40002014 0x304} {
    if {[u32 $address] != $expected} {error "Unexpected startup register $address"}
}
if {$mode eq "candidate"} {
    foreach a {0x40000050 0x4000207c} {if {[u32 $a] != 0xa7170002} {error "Matched-LLR candidate signature mismatch"}}
} else {
    foreach a {0x40000050 0x4000207c} {
        if {[u32 $a] == 0xa7170002} {error "D candidate signature remains after original restore"}
    }
}
if {[u32 $gain_addr] != $expected_gain || [u32 $att_addr] != $expected_att} {error "Runtime role parameters changed"}
puts "STAGE17_LOADED role=$role mode=$mode gain=[u32 $gain_addr] txatt=[u32 $att_addr] plateau=63"
disconnect
