# Observe existing ILA only. Sender must be quiet; no FPGA/RF configuration writes.
# The legacy ILA is in the 200 MHz domain with known timing limitations.
if {$argc!=1} {error "Expected NEW capture directory"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Preserve previous captures"}
file mkdir $out
open_hw
connect_hw_server -url localhost:3121
open_hw_target
set dev [lindex [get_hw_devices -filter {PART =~ "xc7z020*"}] 0]
current_hw_device $dev
set_property PROBES.FILE E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk/System_wrapper_hw_platform_0/System_wrapper.ltx $dev
refresh_hw_device $dev
set ilas {}
foreach item [get_hw_ilas -of_objects $dev] {
    if {[llength [get_hw_probes -of_objects $item -filter {NAME =~ "*rx_intf_0_sample0*"}]]} {lappend ilas $item}
}
if {[llength $ilas]!=1} {error "Ambiguous ILA"}
set ila [lindex $ilas 0]
set depth [get_property CONTROL.DATA_DEPTH $ila]
if {$depth!=1024} {error "Unexpected ILA depth"}
set_property CONTROL.TRIGGER_POSITION 0 $ila
foreach p [get_hw_probes -of_objects $ila] {
    set_property DISPLAY_RADIX HEX $p
    catch {set_property DISPLAY_AS_ENUM false $p}
    set w [get_property WIDTH $p]
    set_property TRIGGER_COMPARE_VALUE "eq${w}'b[string repeat X $w]" $p
}
for {set n 0} {$n<3} {incr n} {
    run_hw_ila -trigger_now $ila
    wait_on_hw_ila -timeout 1 $ila
    set data [upload_hw_ila_data $ila]
    set path [file join $out quiet_${n}.csv]
    write_hw_ila_data -csv_file $path $data
    set f [open $path r];set content [read $f];close $f
    set rows [split [string trimright $content "\r\n"] "\n"]
    set triggers 0
    foreach row [lrange $rows 1 end] {if {[string trim [lindex [split $row ,] 2]] eq "1"} {incr triggers}}
    if {[llength $rows]-1!=$depth || $triggers!=1} {error "Invalid capture rows/trigger"}
    puts "SNR_QUIET_CAPTURE $path rows=$depth"
    after 500
}
close_hw_target
disconnect_hw_server
puts SNR_QUIET_CAPTURE_COMPLETE
