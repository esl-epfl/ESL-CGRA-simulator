from mako.template import Template

def renderim2col(input_channel):

    data = {

    'input_channel': input_channel,

    }
    # Percorso del file template
    template_path = 'im2col-template.h'
    # Carica il template
    template = Template(filename=template_path)
    # Percorso del file di output (può essere lo stesso del template o diverso)
    output_path = 'im2col.c'
    
    # Render del template e scrittura su file
    with open(output_path, 'w') as f:
        f.write(template.render(**data))
    print(f'File im2col.h created/updated')