# Stage18 matched bit/ELF only. Runtime diagnostic register changes, never Flash.
# Stop transmission first. Modes: read; rx <plateau> <dc> <strict|loose>.
if {$argc < 2} {error "Expected role and mode"}
lassign $argv role mode
if {$role ni {sender receiver} || $mode ni {read rx}} {error "Invalid role/mode"}
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
if {$role eq "sender"} {set sdk D:/vivado2018/SDK/2018.3} else {set sdk D:/Xilinx/SDK/2018.3}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n [file join $repo AD9361_test2 Debug AD9361_test2.elf]]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $repo System_wrapper_hw_platform_0 system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xa7170002 0x4000207c 0xa7170002
    0x40000008 0xa704205d 0x40002014 0xa7048304
} {if {[u32 $a] != $expected} {error "Unexpected baseline at $a; no writes"}}
if {$mode eq "rx"} {
    if {$role ne "receiver" || $argc != 5} {error "RX mode needs receiver plateau dc strict|loose"}
    if {[u32 [symbol sample_rate]] != 40000000 || [u32 [symbol gain]] != 66 || [u32 [symbol txatt]] != 25000} {error "Unexpected receiver RF baseline; no writes"}
    lassign [lrange $argv 2 end] plateau dc strictness
    if {$plateau ni {47 55 59 60 63} || $dc ni {32 36 40 44 48 64} || $strictness ni {strict loose}} {error "Outside bounded sweep"}
    set flag [expr {$strictness eq "strict" ? 0x101 : 0x1}]
    if {[u32 0x40002004] ni {1 257} || [u32 0x40002008] ni {2097152 2359296 2621440 2883584 3145728 4194304} || [u32 0x4000200c] ni {47 55 59 60 63}} {error "Unexpected detection registers"}
    foreach {a value} [list 0x40002004 $flag 0x40002008 [expr {$dc << 16}] 0x4000200c $plateau] {
        mwr $a $value
        if {[u32 $a] != $value} {error "Write/readback mismatch at $a"}
    }
}
foreach a {0x40002004 0x40002008 0x4000200c 0x40002010 0x40002014 0x40002048} {puts [format "REG %08X %08X" $a [u32 $a]]}
foreach name {sample_rate gain txatt} {puts "RAM $name [u32 [symbol $name]]"}
if {$role eq "receiver"} {
    foreach name {loopback_rx_done_count rx_frame_valid_count rx_frame_reject_count rx_reject_length_count rx_reject_no_magic_count rx_reject_magic_shift_count rx_reject_header_count loopback_return_packet_count loopback_rx_error_count dma_stall_timeout_count} {
        puts "COUNT $name [u32 [symbol $name]]"
    }
    set a [symbol loopback_return_port]
    set port [expr {([u32 [expr {$a & ~3}]] >> (($a & 3)*8)) & 0xffff}]
    puts [format "GUI_PEER_RAW %08X %d" [u32 [symbol loopback_return_addr]] $port]
}
puts "STAGE19_CONTROL_OK role=$role mode=$mode"
disconnect
