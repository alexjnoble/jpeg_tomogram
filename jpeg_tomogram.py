#!/usr/bin/env python3
#
# Author: Alex J. Noble with help from GPT & Claude, 2023-24 @SEMC, under the MIT License
#
# JPEG Tomogram
#
# This script packs and unpacks 3D MRC files to custom JPEG stacks and vice versa.
# By default, JPEG packing uses 80% quality, which reduces the size to ~10%
# of the original while making minimal visual impact to cryoET tomograms.
# Warning: Only use this for visualization and annotation, not for downstream processing.
#
# Requirement: pip install mrcfile numpy pillow tqdm
# Usage, single-file packing: ./jpeg_tomogram.py pack tomogram.mrc
# Usage, packing a folder of mrc files: ./jpeg_tomogram.py pack tomograms/
# Usage, single-file unpacking ./jpeg_tomogram.py unpack tomogram.jpgs
# Usage, unpacking a folder of jpgs files: ./jpeg_tomogram.py unpack tomograms/
__version__ = "1.0.2"

import io
import os
import sys
import time
import shlex
import fnmatch
import mrcfile
import argparse
import tempfile
import subprocess
import numpy as np
from PIL import Image
from tqdm import tqdm
from pathlib import Path
from multiprocessing import Pool, cpu_count

# ANSI escape codes for colored text
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RESET = "\033[0m"

def print_warning(text):
    """
    Print a warning message in yellow text.

    :param str text: The warning message to be printed
    """
    print(f"{YELLOW}{text}{RESET}")

def print_error(text):
    """
    Print an error message in red text.

    :param str text: The error message to be printed
    """
    print(f"{RED}{text}{RESET}", file=sys.stderr)

def print_success(text):
    """
    Print a success message in green text.

    :param str text: The success message to be printed
    """
    print(f"{GREEN}{text}{RESET}")

def validate_quality(value):
    """
    Validate the JPEG quality value.

    :param int value: The quality value to be validated
    :return int: The validated quality value
    :raises argparse.ArgumentTypeError: If the value is not between 1 and 100
    """
    ivalue = int(value)
    if ivalue < 1 or ivalue > 100:
        raise argparse.ArgumentTypeError(f"Quality must be between 1 and 100, got {value}")
    return ivalue

def save_image(img_data, filename, quality):
    """
    Save a single slice of the MRC data as a JPEG image.

    :param PIL.Image img_data: The image data to be saved
    :param str filename: The filename to save the image to
    :param int quality: The JPEG quality (1-100)
    """
    with open(filename, 'wb') as f, io.BytesIO() as img_buffer:
        img_data.save(img_buffer, format='JPEG', quality=quality)
        img_data = img_buffer.getvalue()
        f.write(len(img_data).to_bytes(4, 'little'))
        f.write(img_data)

def load_image(filename):
    """
    Load a single JPEG image.

    :param str filename: The filename of the image to load
    :return PIL.Image: The loaded image
    """
    with open(filename, 'rb') as f:
        img_size = int.from_bytes(f.read(4), 'little')
        img_data = f.read(img_size)
    with io.BytesIO(img_data) as img_buffer:
        img = Image.open(img_buffer)
        img.load()
    return img

def write_header(mrc, filename):
    """
    Write the header information of the MRC file.

    :param mrcfile.mrcfile.MrcFile mrc: The MRC file object
    :param str filename: The filename to save the header information to
    """
    np.save(filename, mrc.header, allow_pickle=False)

def read_header(filename):
    """
    Read the header information of the MRC file.

    :param str filename: The filename of the JPEG stack
    :return dict: The header information
    """
    base_name = os.path.splitext(filename)[0]  # Remove the .jpgs extension
    header_pattern = f"{base_name}*_header.npy"

    matching_headers = list(Path('.').glob(header_pattern))

    if matching_headers:
        header_file = str(matching_headers[0])
        print(f"Found header file: {header_file}")
        return np.load(header_file)

    print_warning(f"Warning: No header file found matching {header_pattern}. Unpacked MRC file will have default header values.")
    return {}

def save_image_wrapper(args):
    """
    Wrapper function for save_image to be used with multiprocessing.

    :param tuple args: Tuple containing arguments for save_image
    :return: Result of save_image function
    """
    return save_image(*args)

def mrc_to_jpeg_stack(mrc_filename, jpeg_stack_filename, quality, cores=None, verbose=False, quiet=False):
    """
    Convert an MRC file to a JPEG stack.

    :param str mrc_filename: The input MRC filename
    :param str jpeg_stack_filename: The output JPEG stack filename
    :param int quality: The JPEG quality (1-100)
    :param int cores: Number of CPU cores to use (default: None, uses all available cores)
    :param bool verbose: Whether to print verbose output
    :param bool quiet: Whether to suppress all output and progress bars
    :return str: The filename of the created JPEG stack
    """
    if verbose and not quiet:
        print(f"{jpeg_stack_filename}.jpgs is being packed...")
    if cores is None:
        cores = cpu_count()

    with mrcfile.open(mrc_filename, 'r') as mrc:
        data = mrc.data.astype(np.float32)
        mean = np.mean(data)
        std = np.std(data)
        data = (data - mean) / std
        data = data - np.min(data)
        data = data / np.max(data)
        data = (data * 255).astype(np.uint8)

        write_header(mrc, jpeg_stack_filename + '_header.npy')

    # Ensure the jpeg_stack_filename has a non-empty basename
    if os.path.basename(jpeg_stack_filename) == '':
        jpeg_stack_filename = os.path.join(os.path.dirname(jpeg_stack_filename), 'output')

    jpeg_stack_filename = str(Path(jpeg_stack_filename).with_suffix('.jpgs'))

    with tempfile.TemporaryDirectory() as tmpdir:
        if cores > 1:
            with Pool(processes=cores) as pool:
                save_args = [(Image.fromarray(slice), os.path.join(tmpdir, f'{i}.jpg'), quality) for i, slice in enumerate(data)]
                list(pool.imap(save_image_wrapper, save_args) if quiet else
                     tqdm(pool.imap(save_image_wrapper, save_args), 
                          total=len(data), desc="Packing", unit="slice"))
        else:
            for i, slice in (range(len(data)) if quiet else
                             tqdm(enumerate(data), total=len(data), desc="Packing", unit="slice")):
                save_image(Image.fromarray(slice), os.path.join(tmpdir, f'{i}.jpg'), quality)

        with open(jpeg_stack_filename, 'wb') as f:
            f.write(len(data).to_bytes(4, 'little'))
            for i in (range(len(data)) if quiet else
                      tqdm(range(len(data)), desc="Writing", unit="slice")):
                with open(os.path.join(tmpdir, f'{i}.jpg'), 'rb') as img_file:
                    img_data = img_file.read()
                    f.write(len(img_data).to_bytes(4, 'little'))
                    f.write(img_data)
    if not quiet:
        print_success(f"{jpeg_stack_filename} successfully packed!")
    return jpeg_stack_filename

def jpeg_stack_to_mrc(jpeg_stack_filename, mrc_filename, cores=None, verbose=False, quiet=False):
    """
    Convert a JPEG stack to an MRC file.

    :param str jpeg_stack_filename: The input JPEG stack filename
    :param str mrc_filename: The output MRC filename
    :param int cores: Number of CPU cores to use (default: None, uses all available cores)
    :param bool verbose: Whether to print verbose output
    :param bool quiet: Whether to suppress all output and progress bars
    """
    if verbose and not quiet:
        print(f"Input JPEG stack: {jpeg_stack_filename}")
        print(f"Output MRC filename (before processing): {mrc_filename}")

    if cores is None:
        cores = cpu_count()

    # Find the header file
    base_name = os.path.splitext(jpeg_stack_filename)[0]
    header_pattern = f"{base_name}*_header.npy"
    matching_headers = list(Path('.').glob(header_pattern))

    if matching_headers:
        header_file = str(matching_headers[0])
        # Extract the original filename from the header filename
        original_filename = header_file.rsplit('_JPG', 1)[0] + '.mrc'
        mrc_filename = original_filename
    else:
        # If no header file is found, use the input filename without the .jpgs extension
        mrc_filename = base_name + '.mrc'

    if verbose:
        print(f"Output MRC filename (after processing): {mrc_filename}")

    with tempfile.TemporaryDirectory() as tmpdir:
        with open(jpeg_stack_filename, 'rb') as f:
            num_images = int.from_bytes(f.read(4), 'little')

            for i in (range(num_images) if quiet else
                      tqdm(range(num_images), desc="Extracting", unit="slice")):
                img_size = int.from_bytes(f.read(4), 'little')
                img_data = f.read(img_size)
                with open(os.path.join(tmpdir, f'{i}.jpg'), 'wb') as img_file:
                    img_file.write(img_data)

        if cores > 1:
            with Pool(processes=cores) as pool:
                images = list(pool.imap(load_image, 
                    [os.path.join(tmpdir, f'{i}.jpg') for i in range(num_images)]) if quiet else
                    tqdm(pool.imap(load_image, 
                        [os.path.join(tmpdir, f'{i}.jpg') for i in range(num_images)]), 
                        total=num_images, desc="Loading", unit="slice"))
        else:
            images = []
            for i in (range(num_images) if quiet else
                      tqdm(range(num_images), desc="Loading", unit="slice")):
                images.append(load_image(os.path.join(tmpdir, f'{i}.jpg')))

        data = np.array([np.array(img) for img in (images if quiet else
                         tqdm(images, desc="Converting", unit="slice"))])

        header = read_header(jpeg_stack_filename)

        with mrcfile.new(mrc_filename, overwrite=True) as mrc:
            include_fields = ['nx', 'ny', 'nz', 'mode', 'nxstart', 'nystart', 'nzstart', 'mx', 'my', 'mz', 'xlen', 'ylen', 'zlen', 'alpha', 'beta', 'gamma', 'mapc', 'mapr', 'maps', 'amin', 'amax', 'amean', 'ispg', 'extra', 'xorigin', 'yorigin', 'zorigin', 'map', 'machst', 'rms', 'nlabels', 'cella']
            for field in include_fields:
                try:
                    mrc.header[field] = header[field]
                except:
                    pass
            mrc.set_data((data - 128).astype(np.int8))
    if not quiet:
        print_success(f"{mrc_filename} successfully unpacked!")
    return mrc_filename

def report_compression_ratio(input_path, output_files):
    """
    Report the compression ratio achieved by packing.

    :param str input_path: The input file or directory path
    :param list output_files: List of output file paths
    """
    # Normalize the input path to handle cases like '.'
    input_path = Path(input_path).resolve()

    if input_path.is_dir():
        input_files = list(input_path.glob('*.mrc')) + list(input_path.glob('*.rec'))
        input_size = sum(os.path.getsize(str(f)) for f in input_files)
    else:
        input_files = [input_path]
        input_size = os.path.getsize(input_path)

    output_size = sum(os.path.getsize(f) for f in output_files)
    percentage = (1 - output_size / input_size) * 100

    if len(input_files) > 1 or input_path.is_dir():
        print(f"Overall size reduction: {percentage:.2f}%")
    else:
        print(f"Size reduction: {percentage:.2f}%")

def pack_file(args):
    """
    Wrapper function for mrc_to_jpeg_stack to be used with multiprocessing.

    :param tuple args: Tuple containing arguments for mrc_to_jpeg_stack
    :return: Result of mrc_to_jpeg_stack function
    """
    return mrc_to_jpeg_stack(*args)

def unpack_file(args):
    """
    Wrapper function for jpeg_stack_to_mrc to be used with multiprocessing.

    :param tuple args: Tuple containing arguments for jpeg_stack_to_mrc
    :return str: The filename of the unpacked MRC file
    """
    return jpeg_stack_to_mrc(*args)

def main():
    """
    Main function to handle command-line arguments and execute packing or unpacking operations.
    """
    start_time = time.time()

    parser = argparse.ArgumentParser(description='Pack or unpack a JPEG stack.')
    parser.add_argument('mode', choices=['pack', 'unpack'], help='Whether to pack an MRC file into a JPEG stack or unpack a JPEG stack into an MRC file')
    parser.add_argument('input_paths', nargs='+', help='The input file(s) or directory of files (.mrc and .rec supported). Can be a list or a wildcard expression.')
    parser.add_argument('-o', '--output_path', help='The output file or directory (default: same as input path)')
    parser.add_argument('-e', '--external_viewer', help='External program to open the unpacked MRC file(s) (e.g. 3dmod)')
    parser.add_argument('-q', '--quality', type=validate_quality, default=80, help='The quality of the JPEG images in the stack (1-100). Note: values above 95 should be avoided (default: 80)')
    parser.add_argument('-c', '--cores', type=int, default=None, help='Number of CPU cores to use (default: all)')
    parser.add_argument('-V', '--verbose', action='store_true', help='Print verbose output')
    parser.add_argument('--quiet', action='store_true', help='Suppress all output and progress bars')
    parser.add_argument("-v", "--version", action="version", help="Show version number and exit", version=f"JPEG Tomogram v{__version__}")
    args = parser.parse_args()

    # If quiet mode is enabled, suppress all output
    if args.quiet:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

    input_paths = []
    for path in args.input_paths:
        if Path(path).is_dir():
            if args.mode == 'pack':
                input_paths.extend(Path(path).glob('*.mrc'))
                input_paths.extend(Path(path).glob('*.rec'))
            elif args.mode == 'unpack':
                input_paths.extend(Path(path).glob('*.jpgs'))
        else:
            # Handle wildcard patterns (e.g., '*')
            if '*' in path or '?' in path or '[' in path:
                # Filter to include only .mrc and .rec files
                for f in Path().glob(path):
                    if f.suffix in {'.mrc', '.rec'}:
                        input_paths.append(f)
            else:
                # Explicitly check the file extension
                if Path(path).suffix in {'.mrc', '.rec'}:
                    input_paths.append(Path(path))

    if not input_paths:
        print_error(f"Error: No matching files found for input path(s): {args.input_paths}")
        sys.exit(1)

    output_path = Path(args.output_path) if args.output_path else None
    num_files = len(input_paths)
    cores = args.cores if args.cores else cpu_count()
    min_cores = min(cores, num_files)

    if args.mode == 'pack':
        print(f"Packing {num_files} tomograms with JPEG{args.quality} across {min_cores} CPU cores...")
        with Pool(processes=cores) as pool:
            pack_args = [
                (
                    str(f), 
                    str((output_path or f.parent) / (f.stem + f'_JPG{args.quality}')), 
                    args.quality, 
                    1, 
                    args.verbose
                ) 
                for f in input_paths
            ]
            output_files = list(tqdm(pool.imap(pack_file, pack_args), 
                total=len(input_paths), desc="Overall Progress", unit="file"))
        report_compression_ratio(str(args.input_paths[0]), output_files)
    elif args.mode == 'unpack':
        print(f"Unpacking {num_files} tomograms across {min_cores} CPU cores...")
        with Pool(processes=cores) as pool:
            unpack_args = [
                (
                    str(f), 
                    str((output_path or f.parent) / (f.stem.replace(f'_JPG{args.quality}', f'_fromJPG{args.quality}'))), 
                    1, 
                    args.verbose
                ) 
                for f in input_paths
            ]
            mrc_filenames = list(tqdm(pool.imap(unpack_file, unpack_args), 
                total=len(input_paths), desc="Overall Progress", unit="file"))

        if args.external_viewer:
            print(f"Opening {num_files} files with {args.external_viewer}...")
            subprocess.run([args.external_viewer] + mrc_filenames, check=True)

    end_time = time.time()
    if not args.quiet:
        print(f"Total time taken to process {num_files} tomogram{'s' if num_files > 1 else ''}: {end_time - start_time:.2f} seconds")

if __name__ == '__main__':
    main()
