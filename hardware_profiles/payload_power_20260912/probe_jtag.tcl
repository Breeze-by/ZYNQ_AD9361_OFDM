# Read-only cable/device enumeration; no reset, FPGA programming or CPU halt.
if {[llength [info commands open_hw_manager]]} {open_hw_manager} else {open_hw}
connect_hw_server -url localhost:3121
set cables [get_hw_targets]
puts "STAGE17_JTAG_CABLES $cables"
foreach cable $cables {
    current_hw_target $cable
    if {[catch {open_hw_target} message]} {
        puts "STAGE17_JTAG_OPEN_ERROR $message"
    } else {
        puts "STAGE17_JTAG_DEVICES [get_hw_devices]"
        close_hw_target
    }
}
disconnect_hw_server
if {[llength [info commands close_hw_manager]]} {close_hw_manager} else {close_hw}
puts STAGE17_JTAG_PROBE_COMPLETE
