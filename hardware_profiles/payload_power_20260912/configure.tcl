# Diagnostic RAM-only control. Stop sending before changing either board.
# Usage: xsct configure.tcl <sender|receiver> <off|0|1|2|3|4>
if {$argc != 2} {error "Expected role and level"}
lassign $argv role level
if {$role ni {sender receiver} || $level ni {off 0 1 2 3 4}} {error "Invalid role or level"}
set project E:/by2025/AD9361_test_board/AD9361_test2
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $project AD9361_test2.sdk System_wrapper_hw_platform_0 system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
foreach addr {0x40000050 0x4000207c} {
    if {[u32 $addr] != 0xa7170002} {error "Not the Stage 17 matched-LLR candidate; no writes performed"}
}
if {$role eq "sender"} {
    set address 0x40000008
    set base [expr {[u32 $address] & 0x7f}]
    if {$base == 0} {error "Invalid existing scrambler seed"}
    set value [expr {$level eq "off" ? $base : (0xa7002000 | ($level << 16) | $base)}]
} else {
    if {([u32 0x40002010] & 0x11) != 1} {error "Expected original soft LLR decoder mode"}
    set address 0x40002014
    set base [expr {[u32 $address] & 0x3ff}]
    if {$base != 0x304} {error "RX FFT/watchdog settings differ from the qualified baseline"}
    set value [expr {$level eq "off" ? $base : (0xa7008000 | ($level << 16) | $base)}]
}
mwr $address $value
if {[u32 $address] != $value} {error "Power configuration readback mismatch"}
puts [format "STAGE17_POWER role=%s level=%s protected_data_symbols=32 addr=%08x value=%08x" $role $level $address $value]
disconnect
