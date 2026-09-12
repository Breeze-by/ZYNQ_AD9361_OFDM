`timescale 1ns/1ps
module tx_tb;
localparam PAYLOAD_BYTES=128;
reg clk=0;
always #5 clk=~clk;
reg rst=1, start=0;
wire done, started, valid;
reg ready=0;
reg [31:0] cfg=0;
reg [63:0] din=0;
wire [9:0] addr;
wire [15:0] i,q;
reg [63:0] memory [0:1023];
reg [7:0] payload [0:1023];
reg [23:0] signal_bits;
integer k,j,level,fd,sample_no,cycles;
reg [31:0] lfsr;
dot11_tx dut(.clk(clk),.phy_tx_arest(rst),.phy_tx_start(start),
    .phy_tx_done(done),.phy_tx_started(started),.init_pilot_scram_state(7'h7f),
    .init_data_scram_state(7'h7f),.payload_power_config(cfg),
    .bram_din(din),.bram_addr(addr),.result_iq_ready(ready),
    .result_iq_valid(valid),.result_i(i),.result_q(q));
always @(posedge clk) din<=memory[addr];
always @(negedge clk) begin
    cycles=cycles+1;
    // Backpressure is intentional; symbol counters must use accepted samples.
    ready=(cycles%5)==0 && (cycles%13)!=0;
end
initial begin
    cycles=0; lfsr=32'h9361320;
    for(k=0;k<1024;k=k+1) begin
        memory[k]=0;
        lfsr={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
        payload[k]=lfsr[7:0];
    end
    signal_bits=((PAYLOAD_BYTES+4)<<5)|24'h00000b;
    signal_bits[17]=^signal_bits[16:0];
    memory[0]={40'd0,signal_bits};
    for(k=0;k<128;k=k+1)
        for(j=0;j<8;j=j+1) memory[k+2][j*8+:8]=payload[k*8+j];
    fd=$fopen("payload.hex","w");
    for(k=0;k<PAYLOAD_BYTES;k=k+1) $fdisplay(fd,"%02x",payload[k]);
    $fclose(fd);
    for(level=0;level<=4;level=level+1) begin
        rst=1; start=0;
        cfg=32'ha700207f|(level<<16);
        repeat(50) @(negedge clk);
        rst=0;
        repeat(10) @(negedge clk);
        start=1;
        @(posedge clk);
        while(!ready) @(posedge clk);
        @(negedge clk); start=0;
        fd=$fopen($sformatf("tx_level%0d.csv",level),"w");
        $fdisplay(fd,"sample,state,data_symbol,sample_in_symbol,active,i,q,raw_i,raw_q");
        sample_no=0;
        while(!done) begin
            @(posedge clk);
            if(valid && ready) begin
                $fdisplay(fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",sample_no,dut.state3,
                    dut.uep_data_symbol,dut.uep_sample,dut.uep_active,
                    $signed(i),$signed(q),$signed(dut.result_i_unscaled),$signed(dut.result_q_unscaled));
                sample_no=sample_no+1;
            end
        end
        $fclose(fd);
        $display("STAGE17_TX_WAVE level=%0d samples=%0d",level,sample_no);
        repeat(20) @(negedge clk);
    end
    $display("STAGE17_TX_SIM_COMPLETE");
    $finish;
end
initial begin #50000000; $fatal(1,"TX test timeout"); end
integer test_value,test_shift,test_expected,test_actual;
initial begin
    for(test_value=-32768;test_value<=32767;test_value=test_value+1)
        for(test_shift=0;test_shift<=4;test_shift=test_shift+1) begin
            test_expected=test_value<0 ? -test_value : test_value;
            if(test_shift!=0) test_expected=(test_expected+(1<<(test_shift-1)))>>test_shift;
            if(test_value<0) test_expected=-test_expected;
            test_actual=$signed(dut.uep_attenuate(test_value,test_shift));
            if(test_actual!=test_expected) $fatal(1,"Rounding mismatch v=%0d shift=%0d",test_value,test_shift);
        end
    $display("STAGE17_ALL_SIGNED16_ROUNDING_VERIFIED");
end
endmodule
