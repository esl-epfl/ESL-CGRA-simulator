#include <stdio.h>
#include <stdlib.h>

#define MAX_MEMORY_PER_BANK 32768  // 32KB per banco di memoria
#define WORD_SIZE 4  // 32 bit = 4 byte
#define DIMENSIONS_COUNT 7 


unsigned long calculate_memory_usage(int rows, int cols, int channels, int filters) {
    return (unsigned long)((rows * cols * channels * WORD_SIZE) + (3 * 3 * channels * filters * WORD_SIZE) + 2*(filters * (rows-2) * (cols -2) * WORD_SIZE));
}


void generate_combinations(int max_memory_banks, FILE *file) {
    unsigned long max_memory = max_memory_banks * MAX_MEMORY_PER_BANK;
    int dimensions[DIMENSIONS_COUNT] = {16, 32, 48, 64, 80, 96, 144};
    int i, k, l;


    fprintf(file, "Rows & Cols, Channels, Filters, Memory Usage \n");

    for (i = 0; i < DIMENSIONS_COUNT; i++) {
        int rows = dimensions[i];
        int cols = dimensions[i]; // Usa lo stesso valore per le colonne
        for (k = 0; k < DIMENSIONS_COUNT; k++) {
            for (l = 0; l < DIMENSIONS_COUNT; l++) {
                int channels = dimensions[k];
                int filters = dimensions[l];
                unsigned long memory_usage = calculate_memory_usage(rows, cols, channels, filters);

                if (memory_usage <= max_memory) {
                    fprintf(file, "%d, %d, %d, %lukB \n",
                           rows, channels, filters, memory_usage/1024);
                }
            }
        }
    }
}

int main() {
    int max_memory_banks;
    FILE *file;

    printf("Enter the maximum number of memory banks: ");
    scanf("%d", &max_memory_banks);

    file = fopen("output.txt", "w");
    if (file == NULL) {
        fprintf(stderr, "Error opening file.\n");
        return 1;
    }

    generate_combinations(max_memory_banks, file);
    fclose(file);

    printf("Combinations have been written to output.txt\n");

    return 0;
}