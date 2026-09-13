# Inspection and removal trial in an in-memory copy only; never save the project.
set d [file normalize [file join $env(TEMP) ad9361-diag-20260906 stage21-observe-a]]
open_checkpoint [file join $d linked.dcp]
set dot System_i/openofdm_rx_0/inst/dot11_i
set wd System_i/openofdm_rx_0/inst/signal_watchdog_inst
foreach pattern [list $dot/state* $wd/*rst* $wd/*result* $wd/*enable* $wd/*power_trigger*] {
    set nets [get_nets -hierarchical -quiet -filter "NAME =~ $pattern"]
    puts "TRACE_NET $pattern $nets"
}
foreach netname [list System_i/openofdm_rx_0/inst/receiver_rst_reg $dot/state\[0\]] {
    set net [get_nets -quiet $netname]
    puts "TRACE_PIN $netname [get_pins -quiet -of_objects $net -filter {DIRECTION == OUT}]"
}
puts "TRACE_BEFORE [get_debug_cores]"
if {[catch {delete_debug_core [get_debug_cores System_i/ila_0]} e]} {puts "TRACE_REMOVE_ERROR $e"}
puts "TRACE_AFTER [get_debug_cores] CELL=[get_cells -quiet System_i/ila_0]"
foreach pattern [list $dot/reset* System_i/openofdm_rx_0/inst/*receiver_rst*] {
    puts "TRACE_RESET $pattern [get_nets -hierarchical -quiet -filter "NAME =~ $pattern"]"
}
foreach pinname [list $dot/reset $wd/receiver_rst $wd/receiver_rst_reg] {
    set pin [get_pins -quiet $pinname]
    puts "TRACE_PORT $pinname [get_nets -quiet -of_objects $pin]"
}
# HDL-instantiated debug IP needs a netlist-cell removal, not delete_debug_core.
remove_cell [get_cells System_i/ila_0]
puts "TRACE_REMOVED_CELL cores=[get_debug_cores] cell=[get_cells -quiet System_i/ila_0]"
close_design
