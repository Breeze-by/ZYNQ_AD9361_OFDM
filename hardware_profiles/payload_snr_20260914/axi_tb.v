`timescale 1ns/1ps
// Exercise the ACTUAL patched AXI slave and monitor together, without a board.
module axi_tb;
reg clk=0, resetn=0;
always #5 clk=~clk;
reg [6:0] awaddr=0, araddr=0;
reg [31:0] wdata=0;
reg [3:0] wstrb=0;
reg awvalid=0, wvalid=0, arvalid=0;
wire awready, wready, bvalid, arready, rvalid;
wire [1:0] bresp, rresp;
wire [31:0] rdata, control, data, seq, reg5, reg0;
reg payload_valid=0;
reg [31:0] got;
openofdm_rx_s_axi axi (
    .SNR_CONTROL(control), .SNR_DATA(data), .SNR_SEQ(seq),
    .SLV_REG0(reg0), .SLV_REG5(reg5),
    .SLV_REG20(32'd20), .SLV_REG21(32'd21), .SLV_REG30(32'd30), .SLV_REG31(32'ha7170002),
    .S_AXI_ACLK(clk), .S_AXI_ARESETN(resetn),
    .S_AXI_AWADDR(awaddr), .S_AXI_AWPROT(3'd0), .S_AXI_AWVALID(awvalid), .S_AXI_AWREADY(awready),
    .S_AXI_WDATA(wdata), .S_AXI_WSTRB(wstrb), .S_AXI_WVALID(wvalid), .S_AXI_WREADY(wready),
    .S_AXI_BRESP(bresp), .S_AXI_BVALID(bvalid), .S_AXI_BREADY(1'b1),
    .S_AXI_ARADDR(araddr), .S_AXI_ARPROT(3'd0), .S_AXI_ARVALID(arvalid), .S_AXI_ARREADY(arready),
    .S_AXI_RDATA(rdata), .S_AXI_RRESP(rresp), .S_AXI_RVALID(rvalid), .S_AXI_RREADY(1'b1)
);
payload_snr_monitor monitor (
    .clock(clk), .reset(!resetn || reg0[0]), .control(control), .phy_config(reg5),
    .noise_iq(32'h00030004), .noise_strobe(1'b0),
    .payload_iq(32'h00030004), .payload_strobe(payload_valid), .valid_header(1'b0),
    .snapshot_seq(seq), .read_data(data)
);
task write_reg;
input [4:0] address;
input [31:0] value;
input [3:0] bytes;
begin
    @(negedge clk); awaddr={address,2'b00}; wdata=value; wstrb=bytes; awvalid=1; wvalid=1;
    @(posedge clk); while (!(awready && wready)) @(posedge clk);
    @(negedge clk); awvalid=0; wvalid=0;
    @(posedge clk); while (!bvalid) @(posedge clk);
    if (bresp !== 0) $fatal(1,"AXI write error");
    @(negedge clk);
end
endtask
task read_reg;
input [4:0] address;
input [31:0] expected;
begin
    @(negedge clk); araddr={address,2'b00}; arvalid=1;
    @(posedge clk); while (!arready) @(posedge clk);
    @(negedge clk); arvalid=0;
    @(posedge clk); while (!rvalid) @(posedge clk);
    got=rdata;
    if (rresp !== 0 || got !== expected) $fatal(1,"Read %d got %h expected %h",address,got,expected);
    @(negedge clk);
end
endtask
initial begin
    repeat(4) @(negedge clk); resetn=1;
    read_reg(6,0); read_reg(29,32'ha7220001); read_reg(31,32'ha7170002);
    write_reg(5,32'ha7048304,15); read_reg(5,32'ha7048304);
    write_reg(6,32'h12345600,15); read_reg(6,32'h12345600);
    write_reg(6,32'h00ab0000,4); read_reg(6,32'h12ab5600);
    write_reg(6,32'hffffffff,0); read_reg(6,32'h12ab5600);
    write_reg(6,9,15); // payload enable + clear toggle
    repeat(4) @(negedge clk);
    payload_valid=1; repeat(100) @(negedge clk); payload_valid=0;
    repeat(5) @(negedge clk);
    write_reg(6,13,15); // atomic snapshot toggle
    read_reg(22,1); read_reg(28,100);
    write_reg(6,32'h0000020d,15); read_reg(6,32'h0000020d); read_reg(28,2500);
    write_reg(6,32'h0000040d,15); read_reg(28,300);
    write_reg(6,32'h0000060d,15); read_reg(28,400);
    write_reg(6,32'h00000a0d,15); read_reg(28,32'ha7048304);
    payload_valid=1; repeat(20) @(negedge clk); payload_valid=0;
    repeat(5) @(negedge clk);
    write_reg(6,13,15); read_reg(28,100); // bank change must not resnapshot
    write_reg(6,9,15); read_reg(22,2); read_reg(28,120);
    write_reg(6,1,15); repeat(5) @(negedge clk);
    write_reg(6,5,15); read_reg(22,3); read_reg(28,0);
    read_reg(19,0); // legacy CFO override untouched
    $display("SNR_AXI_SIM_COMPLETE"); $finish;
end
initial begin #100000; $fatal(1,"AXI simulation timeout"); end
endmodule
