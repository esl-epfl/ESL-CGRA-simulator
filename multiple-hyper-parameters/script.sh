cd sw/applications/kernel_test/kernels/conv/
python3 render-c.py
cd ~/Documents/GitHub/HEEPsilon
cd sw/applications/kernel_test/utils/
python3 inst_encoder.py ../kernels/conv/ 4x4
cd ~/Documents/GitHub/HEEPsilon
cd sw/applications/kernel_test/kernels/conv/
python3 bitstream.py
cd ~/Documents/GitHub/HEEPsilon
make run-verilator PROJECT=kernel_test
