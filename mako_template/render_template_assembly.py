from mako.template import Template



data = {
    'numb_PE': 16,
    'H_filter': 3,
    'W_filter': 3,
    'size': (3*16)-2,
    
}


filename_path = 'out_template.sat'

template = Template(filename= filename_path)
output_path = 'output_template.sat'

with open(output_path, 'w') as f:
    f.write(template.render(**data))

print('Done!')