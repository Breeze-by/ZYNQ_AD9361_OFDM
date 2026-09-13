# Read the existing synthesis without updating the user's project.
set project E:/by2025/AD9361_test_board/AD9361_test2
set out [file normalize [file join $env(TEMP) ad9361-diag-20260906 stage21-observe-a]]
if {[file exists $out]} {error "Preserve earlier observation build"}
file mkdir $out
open_project -read_only [file join $project AD9361_test2.xpr]
open_run synth_1
puts "STAGE21_DEBUG_CORES [get_debug_cores]"
foreach c [get_debug_cores] {puts "STAGE21_DEBUG $c [list_property $c]"}
puts "STAGE21_ILA_CELL [get_cells -quiet System_i/ila_0]"
foreach pattern {
    *openofdm_rx_0/inst/state* *openofdm_rx_0/inst/receiver_rst*
    *openofdm_rx_0/inst/dot11_i/status_code* *openofdm_rx_0/inst/dot11_i/sample_count*
    *signal_watchdog_inst/running_sum_result* *signal_watchdog_inst/equalizer_monitor_rst*
    *signal_watchdog_inst/sync_short_phase_offset_monitor_rst*
    *sync_long_inst/*state* *sync_long_inst/*mult_stage*
} {
    set found [get_nets -hierarchical -quiet -filter "NAME =~ $pattern"]
    puts "STAGE21_NETS $pattern [llength $found] $found"
}
write_checkpoint [file join $out linked.dcp]
report_utilization -file [file join $out synthesis_utilization.rpt]
puts "STAGE21_SYNTH_CHECKPOINT $out"
close_project
