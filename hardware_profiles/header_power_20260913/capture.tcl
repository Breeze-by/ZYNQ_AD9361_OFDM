# Observe current production ILA without programming FPGA or changing PHY.
if {$argc ni {1 2} || ![regexp {^stage20-[a-z0-9-]+$} [lindex $argv 0]]} {error "Expected fresh stage20 tag and optional image"}
set tag [lindex $argv 0]
set here [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set ltx E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.runs/impl_1/System_wrapper.ltx
if {$argc==2} {
    set kind [lindex $argv 1]
    if {$kind ni {baseline candidate}} {error "Wrong image kind"}
    if {$kind eq "candidate"} {set ltx [file join $here stage20-image System_wrapper.ltx]}
}
open_hw
connect_hw_server -url localhost:3121
open_hw_target
set dev [lindex [get_hw_devices -filter {PART =~ "xc7z020*"}] 0]
current_hw_device $dev
set_property PROBES.FILE $ltx $dev
refresh_hw_device $dev
set ilas {}
foreach item [get_hw_ilas -of_objects $dev] {
    if {[llength [get_hw_probes -of_objects $item -filter {NAME =~ "*rx_intf_0_sample0*"}]]} {lappend ilas $item}
}
if {[llength $ilas]!=1} {error "Ambiguous ILA"}
set ila [lindex $ilas 0]
set depth [get_property CONTROL.DATA_DEPTH $ila]
set_property CONTROL.TRIGGER_POSITION [expr {$depth/2}] $ila
foreach p [get_hw_probes -of_objects $ila] {
    set_property DISPLAY_RADIX HEX $p
    catch {set_property DISPLAY_AS_ENUM false $p}
    set w [get_property WIDTH $p]
    set_property TRIGGER_COMPARE_VALUE "eq${w}'b[string repeat X $w]" $p
}
foreach mode {short data} {
foreach p [get_hw_probes -of_objects $ila] {
    set w [get_property WIDTH $p]
    set_property TRIGGER_COMPARE_VALUE "eq${w}'b[string repeat X $w]" $p
}
if {$mode eq "short"} {
    set_property TRIGGER_COMPARE_VALUE eq1'b1 [get_hw_probes System_i/openofdm_rx_0_short_preamble_detected]
} else {
    set p [get_hw_probes -of_objects $ila -filter {NAME =~ "*openofdm_rx_0_byte_count*"}]
    if {[llength $p]!=1 || [get_property WIDTH $p]!=16} {error "Wrong byte counter probe"}
    set_property TRIGGER_COMPARE_VALUE eq16'h0080 $p
    set_property TRIGGER_COMPARE_VALUE eq1'b1 [get_hw_probes System_i/openofdm_rx_0_byte_out_strobe]
}
for {set n 0} {$n<3} {incr n} {
    set path [file join $here ${tag}_${mode}_${n}.csv]
    if {[file exists $path]} {error "Preserve existing waveform"}
    run_hw_ila $ila
    puts "STAGE20_ILA_ARMED $mode $n depth=$depth"
    wait_on_hw_ila -timeout 50 $ila
    set d [upload_hw_ila_data $ila]
    write_hw_ila_data -csv_file $path $d
    set f [open $path r];set content [read $f];close $f
    set lines [split [string trimright $content "\r\n"] "\n"]
    set triggers 0
    foreach row [lrange $lines 1 end] {if {[string trim [lindex [split $row ,] 2]] eq "1"} {incr triggers}}
    if {[llength $lines]-1!=$depth || $triggers!=1} {error "Invalid capture rows/trigger"}
    puts "STAGE20_CAPTURE $path rows=$depth trigger_rows=$triggers"
}
}
close_hw_target
disconnect_hw_server
puts STAGE20_CAPTURE_COMPLETE
