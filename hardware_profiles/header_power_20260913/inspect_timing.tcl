# Read-only candidate timing inspection. Full legacy timing is not signed off.
set project E:/by2025/AD9361_test_board/ad9361_stage20_header_b_20260913
open_project [file join $project AD9361_test2.xpr]
open_run impl_1
set out [file join $project build_reports]
foreach name {clk_fpga_0 clk_fpga_1 clk_fpga_2 clk_fpga_3} {
    set clk [get_clocks -quiet $name]
    if {[llength $clk]!=1} {error "Missing $name"}
    foreach type {max min} {
        set path [get_timing_paths -quiet -from $clk -to $clk -delay_type $type -max_paths 1]
        if {[llength $path]} {puts "STAGE20_TIMING $name $type [get_property SLACK $path]"}
    }
}
report_timing -from [get_clocks clk_fpga_0] -to [get_clocks clk_fpga_0] -delay_type max -max_paths 12 -file [file join $out stage20_100mhz_setup.rpt]
report_timing -from [get_clocks clk_fpga_0] -to [get_clocks clk_fpga_0] -delay_type min -max_paths 12 -file [file join $out stage20_100mhz_hold.rpt]
puts STAGE20_TIMING_INSPECTED
close_project
