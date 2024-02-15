from mako.template import Template



data ={
    'H_inputs' : 6,
    'W_inputs' : 6,
    'H_filter' : 3,
    'W_filter' : 3,
    'stride' :1,
    'padding' : 0,
    'N_filters' : 1,
    'channels' : 1,
    'batch_size' : 1,
}

filename_path = 'matmul.c'

template = Template(filename= filename_path)

output_path = 'output.c'

with open(output_path, 'w') as f:
    f.write(template.render(**data))

print('Done!')