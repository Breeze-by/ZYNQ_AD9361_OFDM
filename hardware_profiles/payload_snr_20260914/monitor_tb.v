`timescale 1ns/1ps
module monitor_tb;
reg clock=0; always #5 clock=~clock;
reg reset=1;
reg [31:0] control=0, noise_iq=0, payload_iq=0;
reg noise_strobe=0, payload_strobe=0, valid_header=0;
wire [31:0] seq, data;
payload_snr_monitor dut(clock,reset,control,32'ha7048304,
    noise_iq,noise_strobe,payload_iq,payload_strobe,valid_header,seq,data);
task tick; begin @(posedge clock); #1; end endtask
task word;
input [4:0] index; input [31:0] expected;
begin
    @(negedge clock); control[12:8]=index; #1;
    if(data !== expected) begin $display("FAIL word %0d got=%h expected=%h",index,data,expected); $fatal; end
end endtask
task snap; begin @(negedge clock);control[2]=~control[2];tick();end endtask
integer n;
initial begin
    repeat(3) tick(); @(negedge clock); reset=0;control=3;
    noise_iq={16'd3,-16'sd4}; payload_iq={16'd200,16'd300};
    noise_strobe=1;payload_strobe=1;
    repeat(100) tick(); @(negedge clock);noise_strobe=0;payload_strobe=0;
    repeat(4) tick();snap();
    word(0,100);word(1,0);word(2,2500);word(3,0);
    word(4,300);word(5,0);word(6,-400);word(7,32'hffffffff);word(8,0);
    word(10,32'ha7048304);
    // Snapshot held despite continued acquisition and index changes.
    @(negedge clock);noise_strobe=1;repeat(10) tick();word(0,100);
    @(negedge clock);noise_strobe=0;control[0]=0;
    repeat(4) tick();snap();word(0,111);
    // Clear flushes pending pipeline samples and switches to payload mode.
    @(negedge clock);control[3]=~control[3];control[1:0]=1;
    payload_iq={-16'sd5,16'd12};tick();
    @(negedge clock);payload_strobe=1;noise_strobe=1;
    repeat(64) tick();@(negedge clock);payload_strobe=0;noise_strobe=0;
    repeat(4) tick();snap();word(0,64);word(2,10816);word(4,-320);word(5,32'hffffffff);word(6,768);
    // Full negative range squared must not overflow signed 32-bit sum.
    @(negedge clock);control[3]=~control[3];tick();
    @(negedge clock);payload_iq=32'h80008000;payload_strobe=1;valid_header=1;tick();
    @(negedge clock);payload_strobe=0;valid_header=0;repeat(4) tick();snap();
    word(0,1);word(2,32'h80000000);word(3,0);word(8,1);word(9,1);
    word(14,0);
    $display("SNR_MONITOR_SIM_COMPLETE");$finish;
end
initial begin #100000; $fatal(1,"TIMEOUT");end
endmodule
