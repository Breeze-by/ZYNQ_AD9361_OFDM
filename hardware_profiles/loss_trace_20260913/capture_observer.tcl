# Use only the new 100 MHz observer; original ILA is not used for diagnosis.
if {$argc!=2} {error "Expected stage21-tag mode"}
lassign $argv tag mode
if {![regexp {^stage21-[a-z0-9-]+$} $tag] || $mode ni {goodheader badheader ltftimeout dc_ltf dc_signal}} {error "Invalid arguments"}
set d [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set out [file join $d stage21-observe-a]
set csv [file join $d ${tag}_${mode}.csv]
if {[file exists $csv]} {error "Preserve existing capture"}
open_hw
connect_hw_server -url localhost:3121
open_hw_target
set dev [lindex [get_hw_devices -filter {PART =~ "xc7z020*"}] 0]
current_hw_device $dev
set_property PROBES.FILE [file join $out System_wrapper.ltx] $dev
refresh_hw_device $dev
set matches {}
foreach item [get_hw_ilas -of_objects $dev] {
    if {[string match *stage21_ila* [get_property CELL_NAME $item]]} {lappend matches $item}
}
if {[llength $matches]!=1} {error "Missing/ambiguous new observer"}
set ila [lindex $matches 0]
if {[get_property CONTROL.DATA_DEPTH $ila]!=4096} {error "Wrong observer depth"}
set_property CONTROL.TRIGGER_POSITION 2048 $ila
set_property CONTROL.TRIGGER_CONDITION AND $ila
set_property CONTROL.CAPTURE_MODE ALWAYS $ila
set probes [get_hw_probes -of_objects $ila]
foreach p $probes {
    puts "STAGE21_HW_PROBE $p width=[get_property WIDTH $p]"
    set_property DISPLAY_RADIX HEX $p
    catch {set_property DISPLAY_AS_ENUM false $p}
    set_property TRIGGER_COMPARE_VALUE "eq[get_property WIDTH $p]'b[string repeat X [get_property WIDTH $p]]" $p
}
proc select_probe {base} {
    global probes
    set found {}
    foreach p $probes {
        set name [get_property NAME $p]
        set alias "stage21_ila_[file tail $base]"
        if {$name eq $base || [string first "${base}\[" $name]==0 || $name eq $alias} {lappend found $p}
    }
    if {[llength $found]!=1} {error "Ambiguous/missing probe $base: $found"}
    return [lindex $found 0]
}
proc trigger {base value} {
    set p [select_probe $base]
    set_property TRIGGER_COMPARE_VALUE "eq[get_property WIDTH $p]'u$value" $p
}
set dot System_i/openofdm_rx_0/inst/dot11_i
set wd System_i/openofdm_rx_0/inst/signal_watchdog_inst
switch $mode {
    goodheader - badheader {
        trigger System_i/openofdm_rx_0_pkt_header_valid_strobe 1
        trigger System_i/openofdm_rx_0_pkt_header_valid [expr {$mode eq "goodheader"?1:0}]
    }
    ltftimeout {trigger $dot/state 2;trigger $dot/sample_count 321}
    dc_ltf {trigger $dot/state 2;trigger $wd/receiver_rst_reg 1}
    dc_signal {trigger $dot/state 3;trigger $wd/receiver_rst_reg 1}
}
run_hw_ila $ila
puts "STAGE21_ILA_ARMED mode=$mode depth=4096 time=[clock seconds]"
flush stdout
if {[catch {wait_on_hw_ila -timeout 3 $ila} message]} {
    stop_hw_ila $ila
    puts "STAGE21_ILA_TIMEOUT mode=$mode message=$message"
} else {
    set data [upload_hw_ila_data $ila]
    write_hw_ila_data -csv_file $csv $data
    set f [open $csv r];set content [read $f];close $f
    set rows [split [string trimright $content "\r\n"] "\n"]
    set triggers 0
    foreach row [lrange $rows 1 end] {if {[string trim [lindex [split $row ,] 2]] eq "1"} {incr triggers}}
    # 2018.3 may return normally on timeout and stop the core with empty data.
    if {[llength $rows]-1!=4096 || $triggers!=1} {
        file rename $csv ${csv}.invalid
        puts "STAGE21_ILA_NO_VALID_CAPTURE mode=$mode rows=[expr {[llength $rows]-1}] trigger_rows=$triggers time=[clock seconds]"
    } else {
        puts "STAGE21_ILA_CAPTURED path=$csv rows=4096 trigger_rows=$triggers time=[clock seconds]"
    }
}
close_hw_target
disconnect_hw_server
puts STAGE21_CAPTURE_FINISHED
