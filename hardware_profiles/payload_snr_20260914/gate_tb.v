`timescale 1ns/1ps
// The DUT is extracted verbatim from dot11.v by sim_gate.ps1, not a model
// that accidentally replaces the one-cycle header indication by a level.
module gate_tb;
reg clock=0; always #5 clock=~clock;
reg reset=1, sync_long_reset=0, long_preamble_detected=0, sync_long_enable=0;
reg fcs_out_strobe=0, pkt_header_valid=0, pkt_header_valid_strobe=0;
reg pkt_ht=0, phy_len_valid=0, raw_valid=0;
reg [7:0] pkt_rate=8'h0b;
reg [14:0] n_ofdm_sym=344;
reg [15:0] raw_symbol=0;
reg [31:0] payload_power_config=32'ha7048304;
wire sample_valid;
snr_gate_under_test dut(clock,reset,sync_long_reset,long_preamble_detected,
    sync_long_enable,fcs_out_strobe,pkt_header_valid,pkt_header_valid_strobe,
    pkt_ht,pkt_rate,phy_len_valid,n_ofdm_sym,raw_valid,raw_symbol,
    payload_power_config,sample_valid);
reg [31:0] control=1;
wire [31:0] seq, data;
payload_snr_monitor mon(clock,reset,control,payload_power_config,
    32'h77778888,1'b0,32'h0003fffc,sample_valid,
    pkt_header_valid_strobe && pkt_header_valid,seq,data);
integer expected_count=0, checks=0, k;
reg expect_sample=0;
always @(posedge clock) begin
    if(reset) expected_count<=0;
    else if(raw_valid && expect_sample) expected_count<=expected_count+1;
end
task tick; begin @(posedge clock); #1; end endtask
task new_packet;
begin
    @(negedge clock); raw_valid=0; sync_long_reset=1; phy_len_valid=0;
    pkt_header_valid=0; pkt_header_valid_strobe=0; sync_long_enable=1;
    tick(); @(negedge clock); sync_long_reset=0; tick();
    @(negedge clock); long_preamble_detected=1; tick();
    @(negedge clock); long_preamble_detected=0; tick();
end endtask
task header;
input good; input ht; input [7:0] rate;
begin
    @(negedge clock); pkt_header_valid=good; pkt_header_valid_strobe=1;
    pkt_ht=ht; pkt_rate=rate; raw_symbol=3; tick();
    // Actual dot11 S_DECODE_DATA immediately clears BOTH header outputs.
    @(negedge clock); pkt_header_valid=0; pkt_header_valid_strobe=0;
    repeat(4) tick();
    @(negedge clock); phy_len_valid=1; repeat(3) tick();
end endtask
task sample;
input [15:0] symbol; input expected;
begin
    @(negedge clock); raw_valid=1; raw_symbol=symbol; expect_sample=expected; #1;
    checks=checks+1;
    if(sample_valid !== expected) begin
        $display("SNR_GATE_FAIL check=%0d symbol=%0d got=%b expected=%b header_pulse=%b",
            checks,symbol,sample_valid,expected,pkt_header_valid);
        $fatal(1,"HEADER_PULSE_REGRESSION");
    end
    tick(); @(negedge clock); raw_valid=0; expect_sample=0; tick();
end endtask
initial begin
    repeat(3) tick(); @(negedge clock);reset=0;
    new_packet(); header(1,0,8'h0b);
    for(k=0;k<36;k=k+1) sample(k,0); // Includes protected and transition DATA.
    repeat(64) sample(36,1); // OLD GATE FAILS HERE, after header pulse ended.
    sample(346,1); sample(347,0); sample(65535,0);
    @(negedge clock); payload_power_config=32'ha7058304;
    sample(36,0); // Unsupported scale code.
    @(negedge clock); payload_power_config=32'h00048304;
    sample(36,0); // Disabled/invalid power configuration.
    @(negedge clock); payload_power_config=32'ha7048304;
    sample(36,1);
    @(negedge clock); fcs_out_strobe=1;
    sample(36,0); @(negedge clock);fcs_out_strobe=0;sample(36,0);
    new_packet(); header(0,0,8'h0b); sample(36,0); // Rejected header.
    new_packet(); header(1,1,8'h80); sample(36,0); // HT excluded.
    new_packet(); header(1,0,8'h0f); sample(36,0); // Other legacy rate excluded.
    @(negedge clock);pkt_rate=8'h0b;sample(36,0); // Must not relabel old header.
    new_packet(); header(1,0,8'h0b); sample(36,1);
    @(negedge clock); sync_long_enable=0;
    sample(36,0); @(negedge clock);sync_long_enable=1;sample(36,0);
    new_packet(); header(1,0,8'h0b); sample(36,1);
    @(negedge clock);long_preamble_detected=1;
    sample(36,0);@(negedge clock);long_preamble_detected=0;sample(36,0);
    new_packet(); header(1,0,8'h0b); sample(36,1);
    @(negedge clock);sync_long_reset=1;
    sample(36,0);@(negedge clock);sync_long_reset=0;sample(36,0);
    new_packet(); header(1,0,8'h0b); sample(36,1);
    @(negedge clock);reset=1;sample(36,0);
    @(negedge clock);reset=0;sample(36,0); // Watchdog reset cannot retain a packet.
    new_packet(); @(negedge clock);phy_len_valid=1;repeat(4) tick();
    sample(36,0); // Length alone must never open the gate.
    new_packet(); @(negedge clock);n_ofdm_sym=10;
    header(1,0,8'h0b); sample(36,0); // Packet has no weak region.
    new_packet(); @(negedge clock);n_ofdm_sym=344;
    header(1,0,8'h0b); repeat(64) sample(36,1);
    repeat(5) tick(); @(negedge clock);control[2]=~control[2];tick();
    if(data !== expected_count || expected_count != 64)
        $fatal(1,"MONITOR_COUNT got=%0d expected=%0d",data,expected_count);
    @(negedge clock);control[12:8]=2;#1;
    if(data !== 64*25) $fatal(1,"MONITOR_POWER got=%0d",data);
    $display("SNR_GATE_SIM_COMPLETE checks=%0d count=%0d",checks,expected_count);
    $finish;
end
initial begin #1000000; $fatal(1,"TIMEOUT"); end
endmodule
