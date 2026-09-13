# Existing 1024-row/200 MHz ILA only; no FPGA programming.
# Timeout is NOT a valid waveform; require the selected trigger in fresh rows.
if {$argc!=2} {error "Expected stage21-tag goodheader|badheader"}
lassign $argv tag mode
if {![regexp {^stage21-[a-z0-9-]+$} $tag] || $mode ni {goodheader badheader}} {error "Bad capture arguments"}
set d [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set path [file join $d ${tag}_${mode}.csv]
if {[file exists $path]} {error "Preserve existing capture"}
open_hw
connect_hw_server -url localhost:3121
open_hw_target
set dev [lindex [get_hw_devices -filter {PART =~ "xc7z020*"}] 0]
current_hw_device $dev
set_property PROBES.FILE E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.runs/impl_1/System_wrapper.ltx $dev
refresh_hw_device $dev
set ilas {}
foreach item [get_hw_ilas -of_objects $dev] {
    if {[llength [get_hw_probes -of_objects $item -filter {NAME =~ "*rx_intf_0_sample0*"}]]} {lappend ilas $item}
}
if {[llength $ilas]!=1} {error "Ambiguous ILA"}
set ila [lindex $ilas 0]
set depth [get_property CONTROL.DATA_DEPTH $ila]
if {$depth!=1024} {error "Unexpected original ILA depth"}
set_property CONTROL.TRIGGER_POSITION 768 $ila
set_property CONTROL.TRIGGER_CONDITION AND $ila
foreach p [get_hw_probes -of_objects $ila] {
    set_property DISPLAY_RADIX HEX $p
    catch {set_property DISPLAY_AS_ENUM false $p}
    set_property TRIGGER_COMPARE_VALUE "eq[get_property WIDTH $p]'b[string repeat X [get_property WIDTH $p]]" $p
}
set valid [expr {$mode eq "goodheader"?1:0}]
set_property TRIGGER_COMPARE_VALUE eq1'b1 [get_hw_probes System_i/openofdm_rx_0_pkt_header_valid_strobe]
set_property TRIGGER_COMPARE_VALUE eq1'b$valid [get_hw_probes System_i/openofdm_rx_0_pkt_header_valid]
run_hw_ila $ila
puts "STAGE21_ILA_ARMED mode=$mode depth=$depth time=[clock seconds]"
flush stdout
# Vivado wait_on_hw_ila timeout is MINUTES, not seconds (UG835).
if {[catch {wait_on_hw_ila -timeout 3 $ila} message]} {
    stop_hw_ila $ila
    puts "STAGE21_ILA_TIMEOUT mode=$mode message=$message"
} else {
    set data [upload_hw_ila_data $ila]
    write_hw_ila_data -csv_file $path $data
    set f [open $path r];set content [read $f];close $f
    set rows [split [string trimright $content "\r\n"] "\n"]
    set trigger_rows 0
    foreach row [lrange $rows 1 end] {if {[string trim [lindex [split $row ,] 2]] eq "1"} {incr trigger_rows}}
    if {[llength $rows]-1!=$depth || $trigger_rows!=1} {
        file rename $path ${path}.invalid
        puts "STAGE21_ILA_NO_VALID_CAPTURE mode=$mode rows=[expr {[llength $rows]-1}] trigger_rows=$trigger_rows time=[clock seconds]"
    } else {
        puts "STAGE21_ILA_CAPTURED path=$path rows=$depth trigger_rows=$trigger_rows time=[clock seconds]"
    }
}
close_hw_target
disconnect_hw_server
puts STAGE21_CAPTURE_FINISHED
