# No reinitialization. Use only between transmissions on the stage20 candidate.
# Args: sender|receiver read|baseline|boost
if {$argc!=2} {error "Expected role and mode"}
lassign $argv role mode
if {$role ni {sender receiver} || $mode ni {read baseline boost}} {error "Invalid role/mode"}
set d [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
if {$role eq "sender"} {set sdk D:/vivado2018/SDK/2018.3;set elf [file join $d stage20-mailbox candidate.elf]} else {set sdk D:/Xilinx/SDK/2018.3;set elf [file join $d stage20-before-header-power AD9361_test2.elf]}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a]&0xffffffff}]}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $d stage20-image system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xa7170002 0x4000207c 0xa7170002
    0x4000007c 0xa7200001 0x40002074 0xa7200001 0x4000200c 63 0x40002004 0x101
} {if {[u32 $a]!=$expected} {error "Wrong candidate baseline at $a; no writes"}}
if {[u32 0x40000008] ni {2802065501 2802131037} || [u32 0x40002014] ni {2802090756 2802156292}} {error "Unexpected power configuration"}
if {$role eq "receiver" && [u32 0x40002008]!=0x002c0000} {error "Receiver DC44 missing"}
if {[u32 [symbol sample_rate]]!=40000000} {error "Wrong sample rate"}
if {$mode ne "read"} {
    set code [expr {$mode eq "baseline"?4:5}]
    if {$role eq "sender"} {
        set requested [expr {$mode eq "baseline"?16000:13500}]
        if {[u32 [symbol gain]]!=36 || [u32 0x40000004]!=127} {error "Wrong sender baseline"}
        set a [symbol stage20_result]
        # Result cache line is flushed by the temporary sender application.
        set count [u32 [expr {$a+4}]]
        set command [expr {0xa720007f | (($requested/250)<<8)}]
        mwr 0x40000004 $command
        after 1000
        if {[u32 0x40000004]!=127 || [u32 $a]!=0xa7200001 || [u32 [expr {$a+4}]]!=$count+1 || [u32 [expr {$a+8}]]!=$requested || [u32 [expr {$a+12}]]!=0 || [u32 [expr {$a+16}]]!=$requested || [u32 [expr {$a+20}]]!=$requested} {error "Attenuation API readback failed; stop tests"}
        puts "ADI_TX_ATT_CONFIRMED both_channels_mdb=$requested command_count=[u32 [expr {$a+4}]]"
    } elseif {[u32 [symbol gain]]!=66} {error "Wrong receiver gain"}
    foreach {a value} [list 0x40000008 [expr {0xa700205d|($code<<16)}] 0x40002014 [expr {0xa7008304|($code<<16)}]] {
        mwr $a $value
        if {[u32 $a]!=$value} {error "Power configuration write mismatch"}
    }
}
foreach a {0x40000004 0x40000008 0x40002004 0x40002008 0x4000200c 0x40002014} {puts [format "REG %08X %08X" $a [u32 $a]]}
foreach name {sample_rate gain} {puts "RAM $name [u32 [symbol $name]]"}
# Sender txatt shadow may be cached. ATT_RESULT4/5 below are ADI API reads,
# explicitly flushed by the mailbox; use those as attenuation evidence.
if {$role eq "receiver"} {
    foreach name {loopback_rx_done_count rx_frame_valid_count rx_frame_reject_count rx_reject_length_count rx_reject_no_magic_count rx_reject_magic_shift_count rx_reject_header_count loopback_return_packet_count loopback_rx_error_count dma_stall_timeout_count} {puts "COUNT $name [u32 [symbol $name]]"}
} else {
    set a [symbol stage20_result]
    for {set n 0} {$n<6} {incr n} {puts "ATT_RESULT$n [u32 [expr {$a+4*$n}]]"}
}
puts "STAGE20_CONTROL_OK role=$role mode=$mode"
disconnect
