set out [file normalize [file join $env(TEMP) ad9361-diag-20260906 stage21-observe-a]]
set checkpoint routed.dcp
if {$argc==1 && [lindex $argv 0] eq "repaired"} {set checkpoint routed-repaired.dcp}
open_checkpoint [file join $out $checkpoint]
set clk [get_clocks -of_objects [get_pins {System_i/processing_system7_0/inst/PS7_i/FCLKCLK[0]}]]
if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-10.0)>0.001} {error "Missing 100 MHz clock"}
set failed 0
foreach type {max min} {
    set path [get_timing_paths -from $clk -to $clk -delay_type $type -max_paths 1]
    if {[llength $path]!=1} {error "Missing timed 100 MHz path"}
    set slack [get_property SLACK $path]
    puts "STAGE21_CLOCK100 type=$type slack=$slack endpoint=[get_property ENDPOINT_PIN $path]"
    if {$slack<0} {set failed 1}
}
set regs [get_cells -hierarchical -filter {NAME =~ stage21_ila/* && IS_SEQUENTIAL == 1}]
if {![llength $regs]} {error "No observer registers"}
foreach type {max min} {
    set path [get_timing_paths -to $regs -delay_type $type -max_paths 1]
    if {[llength $path]!=1} {error "No observer timing path"}
    set slack [get_property SLACK $path]
    puts "STAGE21_OBSERVER_TIMING type=$type slack=$slack endpoint=[get_property ENDPOINT_PIN $path]"
    if {$slack<0} {set failed 1}
    report_timing -to $regs -delay_type $type -max_paths 10 -file [file join $out observer_${type}.rpt]
}
report_clocks -file [file join $out clocks.rpt]
close_design
if {$failed} {error "Observer/100MHz timing failed; do not load this candidate"}
puts "STAGE21_OBSERVER_TIMING_PASSED local_100mhz_only_not_global_signoff"
