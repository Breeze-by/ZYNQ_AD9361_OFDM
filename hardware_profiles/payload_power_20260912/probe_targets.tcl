connect -url tcp:127.0.0.1:3121
for {set n 0} {$n<10} {incr n} {
    if {[llength [targets -target-properties -filter {name =~ "APU"}]]} {break}
    after 1000
}
puts "STAGE17_TARGETS [targets]"
if {[llength [targets -target-properties -filter {name =~ "APU"}]] != 1} {error "Expected one Zynq APU"}
puts STAGE17_APU_FOUND
disconnect
