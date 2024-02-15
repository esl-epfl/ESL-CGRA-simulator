from mako.template import Template
import exporter



def renderassembly(input_dim, filter_dimension, input_channel, output_channel):
    folders_available = ['ws', 'oc', 'im2c-ic', 'im2c-oc']
    folder = '4x4'
    folder_juan = 'cd sw/applications/kernel_test/utils/'

    data = {
        'output_row': input_dim-filter_dimension+1,
        'output_col': input_dim-filter_dimension+1,
        'input_channel': input_channel,
        'output_channel': output_channel,
    }



    # Percorso del file template
    template_path = f'instructions.csv'

    # Carica il template
    template = Template(filename=template_path)
    # Percorso del file di output (può essere lo stesso del template o diverso)
    output_path = f'instruction/instructions_input-{input_dim}_ic-{input_channel}_oc-{output_channel}.csv'  # Cambia il nome se vuoi sovrascrivere

    # Render del template e scrittura su file
    with open(output_path, 'w') as f:
        f.write(template.render(**data))
    print(f'File created/updated in {folder}')
    exporter.export(output_path, f'{folder}/out.sat')
    