# Repair only the one RTSTAT-5 incomplete branch in the independent checkpoint.
set out [file normalize [file join $env(TEMP) ad9361-diag-20260906 stage21-observe-a]]
if {[file exists [file join $out routed-repaired.dcp]] || [file exists [file join $out System_wrapper.bit]]} {error "Preserve existing repair"}
open_checkpoint [file join $out routed.dcp]
set name {System_i/axi_dma_0/U0/I_PRMRY_DATAMOVER/GEN_S2MM_FULL.I_S2MM_FULL_WRAPPER/GEN_ENABLE_INDET_BTT_SF.I_INDET_BTT/I_DATA_FIFO/BLK_MEM.I_SYNC_FIFOGEN_FIFO/xpm_fifo_instance.xpm_fifo_sync_inst/xpm_fifo_base_inst/rst_d1_inst/ram_wr_en_pf}
set net [get_nets -quiet [list $name]]
if {[llength $net]!=1} {error "Missing exact RTSTAT-5 target"}
puts "STAGE21_ROUTE_REPAIR $net"
route_design -unroute -nets $net
route_design -nets $net
write_checkpoint [file join $out routed-repaired.dcp]
report_timing_summary -delay_type min_max -max_paths 30 -file [file join $out timing-repaired.rpt]
report_drc -file [file join $out drc-repaired.rpt]
write_bitstream [file join $out System_wrapper.bit]
puts "STAGE21_REPAIRED_OBSERVER_BUILT $out"
close_design
