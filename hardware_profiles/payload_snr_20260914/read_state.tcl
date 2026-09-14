# Non-resetting readback of the current SNR image, using fresh ELF symbols.
if {$argc!=1 || [lindex $argv 0] ni {sender receiver}} {error "Expected sender|receiver"}
set role [lindex $argv 0]
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
set sdk [expr {$role eq "sender" ? "D:/vivado2018/SDK/2018.3" : "D:/Xilinx/SDK/2018.3"}]
set elf [file join $repo AD9361_test2 Debug AD9361_test2.elf]
set bin [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin]
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
foreach a {0x40002004 0x40002008 0x4000200c 0x40002010 0x40002014 0x40002018 0x40002048} {puts [format "REG %08X %08X" $a [u32 $a]]}
# Check a code prefix before using the ELF's data addresses. This is not a
# complete RAM/ELF identity proof; record disk hashes separately.
set addr [symbol net_snr_request]
set dis [exec [file join $bin arm-none-eabi-objdump.exe] -d --start-address=$addr --stop-address=[expr {$addr+32}] $elf]
set checked 0
foreach line [split $dis \n] {
    if {[regexp {^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s} $line unused a word]} {
        set actual [u32 [scan $a %x]]
        if {$actual != ([scan $word %x]&0xffffffff)} {error [format "Running code differs from disk ELF at %s: RAM=%08X ELF=%s; do not read RAM symbols" $a $actual $word]}
        incr checked
    }
}
if {$checked!=8} {error "No complete SNR code prefix verification"}
puts "SNR_ELF_CODE_PREFIX_VERIFIED words=$checked"
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xa7170002 0x4000207c 0xa7170002 0x40002074 0xa7220001
    0x40000008 0xa704205d 0x40002014 0xa7048304
} {if {[u32 $a]!=$expected} {error "Unexpected image/config $a"}}
foreach name {sample_rate gain txatt} {puts "RAM $name [u32 [symbol $name]]"}
if {$role eq "receiver"} {
    foreach name {loopback_rx_done_count rx_frame_valid_count rx_frame_reject_count rx_reject_length_count rx_reject_no_magic_count rx_reject_magic_shift_count rx_reject_header_count loopback_return_packet_count loopback_rx_error_count dma_stall_timeout_count} {puts "COUNT $name [u32 [symbol $name]]"}
    set a [symbol loopback_return_port]
    set port [expr {([u32 [expr {$a&~3}]]>>(($a&3)*8))&0xffff}]
    puts [format "GUI_PEER_RAW %08X %d" [u32 [symbol loopback_return_addr]] $port]
}
puts "SNR_STATE_OK role=$role"
disconnect
