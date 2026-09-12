# Bounded experimental load or restoration of each board's own stage20 backup.
# Neither mode edits original SDK artifacts or writes Flash/SD.
if {$argc!=2} {error "Expected sender|receiver candidate|restore"}
lassign $argv role mode
if {$role ni {sender receiver} || $mode ni {candidate restore}} {error "Invalid role/mode"}
set d [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set backup [file join $d stage20-before-header-power]
if {$role eq "sender"} {set sdk D:/vivado2018/SDK/2018.3;set gain 36;set att 16000} else {set sdk D:/Xilinx/SDK/2018.3;set gain 66;set att 25000}
set elf [file join $backup AD9361_test2.elf]
set image $backup
if {$mode eq "candidate"} {
    set image [file join $d stage20-image]
    if {$role eq "sender"} {set elf [file join $d stage20-mailbox candidate.elf]}
}
foreach f [list $elf [file join $image System_wrapper.bit] [file join $image system.hdf] [file join $image ps7_init.tcl]] {if {![file isfile $f]} {error "Missing $f"}}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a]&0xffffffff}]}
proc step {s} {puts "STAGE20_LOAD_STEP $s";flush stdout}
step connect
connect -url tcp:127.0.0.1:3121
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
ps7_post_config
step download_role_elf
dow $elf
if {[u32 [symbol gain]]!=$gain || [u32 [symbol txatt]]!=$att || [u32 [symbol sample_rate]]!=40000000} {error "Wrong role ELF; CPU stopped"}
step run
con
after 12000
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $image system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xa7170002 0x4000207c 0xa7170002
    0x40000008 0xa704205d 0x40002014 0xa7048304
    0x40002004 0x101 0x40002008 0x00300000 0x4000200c 63
} {if {[u32 $a]!=$expected} {error "Unexpected startup register $a"}}
if {$mode eq "candidate"} {
    foreach a {0x4000007c 0x40002074} {if {[u32 $a]!=0xa7200001} {error "Candidate capability missing"}}
} else {
    foreach a {0x4000007c 0x40002074} {if {[u32 $a]!=0} {error "Candidate still present after restoration"}}
}
if {$role eq "receiver"} {
    mwr 0x40002008 0x002c0000
    if {[u32 0x40002008]!=0x002c0000} {error "DC44 runtime restoration failed"}
}
puts "STAGE20_LOAD_OK role=$role mode=$mode gain=$gain atten_mdb=$att power_code=4 receiver_dc=44"
disconnect
