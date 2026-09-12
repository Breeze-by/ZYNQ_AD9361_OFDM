# Numerical TX, saturation, and per-sample LLR matching checks, not full RX PHY.
set here [file dirname [file normalize [info script]]]
set candidate E:/by2025/AD9361_test_board/ad9361_stage20_header_b_20260913
set old E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk/hardware_profiles/payload_power_20260912
set out E:/by2025/AD9361_test_board/stage20-unit-sim-b
if {[file exists $out]} {error "Preserve existing simulation"}
file mkdir $out
proc read_text {p} {set f [open $p r];set s [read $f];close $f;return $s}
proc write_text {p s} {set f [open $p w];puts -nonewline $f $s;close $f}
set tb [read_text [file join $old tx_tb.v]]
set tb [string map [list {PAYLOAD_BYTES=128} {PAYLOAD_BYTES=1024} {level<=4} {level<=5} {test_shift<=4} {test_shift<=5} {if(test_shift!=0) test_expected=(test_expected+(1<<(test_shift-1)))>>test_shift;} {if(test_shift==5) test_expected=(test_expected*3+32)>>6;
            else if(test_shift!=0) test_expected=(test_expected+(1<<(test_shift-1)))>>test_shift;} {STAGE17_} {STAGE20_}] $tb]
write_text [file join $out tx_tb.v] $tb
set src [file join $candidate ip_repo openofdm_tx src]
create_project stage20_tx [file join $out tx] -part xc7z020clg484-1
set_property target_simulator XSim [current_project]
set_property XPM_LIBRARIES {XPM_CDC XPM_MEMORY XPM_FIFO} [current_project]
add_files [glob [file join $src *.v]]
set_property include_dirs $src [get_filesets sources_1]
foreach mem [glob [file join $src *.mem]] {add_files -fileset sim_1 $mem;set_property file_type {Memory Initialization Files} [get_files $mem]}
add_files -fileset sim_1 [file join $out tx_tb.v]
set_property file_type SystemVerilog [get_files tx_tb.v]
set_property top tx_tb [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
close_project

set tb [read_text [file join $old llr_tb.v]]
set tb [string map [list {shift=n%5} {shift=n%6} {expected[0]=(-64'sd4096*$signed(ci)*64'sd8) >>> (16+2*shift);} {expected[0]=(-64'sd4096*$signed(ci)*64'sd8) >>> 16;
            if(shift==5) expected[0]=(expected[0]*9) >>> 12;
            else expected[0]=expected[0] >>> (2*shift);} {STAGE17_} {STAGE20_}] $tb]
write_text [file join $out llr_tb.v] $tb
set vh [read_text [file join $candidate ip_repo openofdm_rx src payload_power_rx.vh]]
if {![regexp {function \[15:0\] uep_restore;.*?endfunction} $vh restore]} {error "Missing actual RX function"}
set tb "`timescale 1ns/1ps\nmodule restore_tb;\n$restore\n"
append tb {
integer value, amount, actual, checked=0;
reg signed [63:0] expected, ideal;
task verify;
input signed [31:0] v;
input [2:0] a;
begin
    if(a==5) begin
        expected=($signed(v)*64'sd21845) >>> 10;
        if(v>1535) expected=32767;
        if(v< -1536) expected=-32768;
    end else begin
        expected=$signed(v)*64'sd1;
        expected=expected <<< a;
        if(expected>32767) expected=32767;
        if(expected< -32768) expected=-32768;
    end
    actual=$signed(uep_restore(v,a));
    if(actual!==expected) $fatal(1,"RESTORE v=%0d a=%0d got=%0d expected=%0d",v,a,actual,expected);
    if(a==5 && v>=-1536 && v<=1535) begin
        ideal=$signed(v)*64'sd64;
        ideal=ideal>=0 ? ideal/3 : -((-ideal+2)/3);
        if(actual-ideal>1 || ideal-actual>1) $fatal(1,"Reciprocal approximation exceeds 1 LSB");
    end
    checked=checked+1;
end
endtask
initial begin
    for(value=-65536;value<=65535;value=value+1)
        for(amount=0;amount<=5;amount=amount+1) verify(value,amount);
    for(amount=0;amount<=5;amount=amount+1) begin
        verify(32'sh80000000,amount);verify(32'sh7fffffff,amount);
    end
    $display("STAGE20_RESTORE_UNIT_COMPLETE checked=%0d",checked);
    $finish;
end
endmodule
}
write_text [file join $out restore_tb.v] $tb
puts STAGE20_SIM_FIXTURES_READY
