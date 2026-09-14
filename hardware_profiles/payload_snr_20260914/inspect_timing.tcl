# Read-only check of the independent candidate, not timing signoff.
if {$argc ni {1 2}} {error "Expected project directory and optional reports directory"}
set project [file normalize [lindex $argv 0]]
open_project [file join $project AD9361_test2.xpr]
open_run impl_1
set out [file join $project build_reports]
if {$argc==2} {set out [file normalize [lindex $argv 1]]}
if {![file isdirectory $out]} {error "Reports directory missing"}
foreach name {clk_fpga_0 clk_fpga_1 clk_fpga_2 clk_fpga_3} {
    set clk [get_clocks -quiet $name]
    if {[llength $clk]!=1} {error "Missing $name"}
    foreach type {max min} {
        set p [get_timing_paths -quiet -from $clk -to $clk -delay_type $type -max_paths 1]
        if {[llength $p]} {puts "SNR_TIMING $name $type [get_property SLACK $p]"}
    }
}
set monitor [get_cells -hier -quiet -filter {NAME =~ *payload_snr_monitor_i* && IS_SEQUENTIAL}]
if {![llength $monitor]} {error "Missing monitor sequential cells"}
puts "SNR_MONITOR_CELLS [llength $monitor]"
foreach type {max min} {
    foreach direction {from to} {
        if {$direction eq "from"} {
            set paths [get_timing_paths -quiet -from $monitor -delay_type $type -max_paths 8]
            report_timing -from $monitor -delay_type $type -max_paths 8 -file [file join $out snr_${direction}_${type}.rpt]
        } else {
            set paths [get_timing_paths -quiet -to $monitor -delay_type $type -max_paths 8]
            report_timing -to $monitor -delay_type $type -max_paths 8 -file [file join $out snr_${direction}_${type}.rpt]
        }
        if {![llength $paths]} {error "No monitor $direction $type timing"}
        puts "SNR_MONITOR_TIMING $direction $type [get_property SLACK [lindex $paths 0]]"
    }
}
puts SNR_TIMING_INSPECTED
close_project
