# Current original Stage18 image only. No reset, no RF-parameter writes.
# The watchdog selector is temporarily changed and restored, never cleared.
if {$argc ni {1 2} || [lindex $argv 0] ni {sender receiver}} {error {Expected sender|receiver with optional quiet}}
set role [lindex $argv 0]
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
if {$role eq "sender"} {set sdk D:/vivado2018/SDK/2018.3} else {set sdk D:/Xilinx/SDK/2018.3}
set elf [file join $repo AD9361_test2 Debug AD9361_test2.elf]
if {$argc==2} {
    if {$role ne "receiver" || [lindex $argv 1] ne "quiet"} {error "Invalid temporary ELF selector"}
    set elf [file normalize [file join $env(TEMP) ad9361-diag-20260906 stage21-quiet candidate.elf]]
}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a]&0xffffffff}]}
connect -url tcp:127.0.0.1:3121
for {set n 0} {$n<10} {incr n} {
    if {[llength [targets -target-properties -filter {name =~ "APU"}]]>0} {break}
    after 1000
}
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $repo System_wrapper_hw_platform_0 system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xa7170002 0x4000207c 0xa7170002
    0x40000008 0xa704205d 0x40002014 0xa7048304
    0x4000007c 0 0x40002074 0
} {if {[u32 $a]!=$expected} {error "Unexpected baseline $a; stop diagnostics"}}
foreach a {0x40002004 0x40002008 0x4000200c 0x40002010 0x40002014 0x40002048 0x4000204c 0x40002050 0x40002054} {puts [format "REG %08X %08X" $a [u32 $a]]}
foreach name {sample_rate gain txatt} {puts "RAM $name [u32 [symbol $name]]"}
if {$role eq "receiver"} {
    foreach name {loopback_rx_done_count rx_frame_valid_count rx_frame_reject_count rx_reject_length_count rx_reject_no_magic_count rx_reject_magic_shift_count rx_reject_header_count loopback_return_packet_count loopback_rx_error_count dma_stall_timeout_count} {puts "COUNT $name [u32 [symbol $name]]"}
    set old [u32 0x40002044]
    set failed [catch {
        foreach event {0 1 2 3 4} {
            mwr 0x40002044 [expr {($old&0xfffffff8)|$event}]
            after 2
            puts "WATCHDOG $event [expr {[u32 0x40002078]&0x3fffff}]"
        }
    } message options]
    mwr 0x40002044 $old
    if {[u32 0x40002044]!=$old} {error "Selector restoration failed"}
    if {$failed} {return -options $options $message}
    set a [symbol loopback_return_port]
    set port [expr {([u32 [expr {$a&~3}]]>>(($a&3)*8))&0xffff}]
    puts [format "GUI_PEER_RAW %08X %d" [u32 [symbol loopback_return_addr]] $port]
}
puts "STAGE21_STATE_OK role=$role"
disconnect
