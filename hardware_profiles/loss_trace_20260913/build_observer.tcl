# Independent netlist-only observation; all user RTL and project artifacts stay intact.
set project E:/by2025/AD9361_test_board/AD9361_test2
set out [file normalize [file join $env(TEMP) ad9361-diag-20260906 stage21-observe-a]]
if {[file exists [file join $out optimized.dcp]]} {error "Preserve existing build"}
open_checkpoint [file join $out linked.dcp]
# Vivado 2018.3 protects the HDL-instantiated original ILA from netlist removal.
# Retain it, but capture exclusively with the new core and check its timing.
set clknet [get_nets -of_objects [get_pins {System_i/processing_system7_0/inst/PS7_i/FCLKCLK[0]}]]
if {[llength $clknet]!=1} {error "Ambiguous 100 MHz clock"}
create_debug_core stage21_ila ila
set core [get_debug_cores stage21_ila]
foreach {property value} {C_DATA_DEPTH 4096 C_ADV_TRIGGER true C_EN_STRG_QUAL true C_INPUT_PIPE_STAGES 1 C_TRIGIN_EN false C_TRIGOUT_EN false ALL_PROBE_SAME_MU true ALL_PROBE_SAME_MU_CNT 2} {set_property $property $value $core}
connect_debug_port stage21_ila/clk $clknet
disconnect_debug_port dbg_hub/clk
connect_debug_port dbg_hub/clk $clknet
set_property C_CLK_INPUT_FREQ_HZ 100000000 [get_debug_cores dbg_hub]
proc probe_bus {base width} {
    set nets {}
    for {set i 0} {$i<$width} {incr i} {
        set name [expr {$width==1?$base:[format {%s[%d]} $base $i]}]
        set n [get_nets -quiet [list $name]]
        if {[llength $n]!=1} {error "Missing net $name"}
        lappend nets $n
    }
    return $nets
}
set dot System_i/openofdm_rx_0/inst/dot11_i
set wd System_i/openofdm_rx_0/inst/signal_watchdog_inst
set mapping [list \
    iq System_i/rx_intf_0_sample0 32 \
    sample_strobe System_i/rx_intf_0_sample_strobe 1 \
    state $dot/state 5 \
    ltf_sample_count $dot/sample_count 9 \
    ltf_state $dot/sync_long_inst/state__0 3 \
    mult_stage $dot/sync_long_inst/mult_stage__0 3 \
    short_detect System_i/openofdm_rx_0_short_preamble_detected 1 \
    long_detect System_i/openofdm_rx_0_long_preamble_detected 1 \
    header_valid System_i/openofdm_rx_0_pkt_header_valid 1 \
    header_strobe System_i/openofdm_rx_0_pkt_header_valid_strobe 1 \
    fcs_strobe System_i/openofdm_rx_0_fcs_out_strobe 1 \
    fcs_ok System_i/openofdm_rx_0_fcs_ok 1 \
    dc_event_ungated $wd/receiver_rst_reg 1 \
    cfo_event_ungated $wd/sync_short_phase_offset_monitor_rst 1 \
    sign_sum_i $wd/signal_watchdog_running_sum_inst/running_sum_result0 8 \
    sign_sum_q $wd/signal_watchdog_running_sum_inst/running_sum_result1 8 \
    packet_length System_i/openofdm_rx_0_pkt_len 16 \
    packet_rate System_i/openofdm_rx_0_pkt_rate 8 \
    demod System_i/openofdm_rx_0_demod_is_ongoing 1]
set pnum 0
set f [open [file join $out probe-map.txt] w]
foreach {label net width} $mapping {
    if {$pnum>0} {create_debug_port stage21_ila probe}
    set port [get_debug_ports stage21_ila/probe$pnum]
    set_property port_width $width $port
    set_property PROBE_TYPE DATA_AND_TRIGGER $port
    connect_debug_port $port [probe_bus $net $width]
    puts $f "$pnum $label $width $net"
    puts "STAGE21_PROBE $pnum $label $width"
    incr pnum
}
close $f
opt_design
write_checkpoint [file join $out optimized.dcp]
read_checkpoint -incremental [file join $project AD9361_test2.runs impl_1 System_wrapper_routed.dcp]
place_design
route_design
write_checkpoint [file join $out routed.dcp]
report_timing_summary -delay_type min_max -max_paths 30 -file [file join $out timing.rpt]
report_utilization -file [file join $out utilization.rpt]
report_drc -file [file join $out drc.rpt]
write_debug_probes [file join $out System_wrapper.ltx]
# Produce the bit for review, but do not download it here.
write_bitstream [file join $out System_wrapper.bit]
puts "STAGE21_OBSERVER_BUILD_DONE $out"
close_design
