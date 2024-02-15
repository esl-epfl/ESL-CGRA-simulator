from mako.template import Template
import renderassembly
import renderim2col


input_dim = 16
filter_dimension = 3
input_channel = 128
output_channel = 48

data = {
    'input_dim': input_dim,
    'output_row': input_dim-filter_dimension+1,
    'output_col': input_dim-filter_dimension+1,
    'input_channel': input_channel,
    'output_channel': output_channel,
}
# Percorso del file template
template_path = 'conv-template.h'
# Carica il template
template = Template(filename=template_path)
# Percorso del file di output (può essere lo stesso del template o diverso)
output_path = 'conv.h'

# Render del template e scrittura su file
with open(output_path, 'w') as f:
    f.write(template.render(**data))
print(f'File conv.h created/updated')

renderassembly.renderassembly(input_dim, filter_dimension, input_channel, output_channel)
renderim2col.renderim2col(input_channel)

