# JPEG Tomogram Conversion Script

Pack and unpack 3D MRC files to JPEG stacks for visualization to save space. This tool is intended for visualization and annotation of cryoET tomograms.

## Warning
This tool should not be used for downstream processing as the JPEG format causes a loss in precision.

## Requirements
This script requires Python 3 and the following Python libraries:
- mrcfile
- numpy
- Pillow

You can install these libraries using pip:
```
pip install mrcfile numpy Pillow
```

## Usage

You can use this script to pack or unpack single files or entire directories. Here are some examples:

To pack a single MRC file into a JPEG stack:
```
./jpeg_tomogram.py pack tomogram.mrc
```

To pack a directory of MRC files into JPEG stacks:
```
./jpeg_tomogram.py pack tomograms/
```

To unpack a single JPEG stack into a MRC file:
```
./jpeg_tomogram.py unpack tomogram.jpgs
```

To unpack a directory of JPEG stacks into MRC files:
```
./jpeg_tomogram.py unpack tomograms/
```

## Options

This script supports several optional arguments:

- `-o`, `--output_path`: Specify the output file or directory. By default, the output will be saved in the same location as the input.
- `-e`, `--external_viewer`: Specify an external program to open the unpacked MRC file.
- `-q`, `--quality`: Specify the quality of the JPEG images in the stack. The default quality is 80, and values above 95 should be avoided.
- `-c`, `--cores`: Specify the number of CPU cores to use. By default, the script will use all available cores.
- `-v`, `--verbose`: Enable verbose output.

## Example with Options

Here is an example of using the script with some optional arguments:

```
./jpeg_tomogram.py pack tomogram.mrc -o output_directory/ -q 90 -c 4 -v
```

## Author

This script was written by Alex J. Noble with assistance from OpenAI's GPT-4 model, July 2023.

In this example, the script will pack the `tomogram.mrc` file into a JPEG stack with a quality of 90. The output will be saved in `output_directory/`. The script will use 4 CPU cores, and verbose output will be enabled.

---
