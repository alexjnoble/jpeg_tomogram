#!/usr/bin/env python3
#
# Author: Alex J. Noble with help from GPT4, July 2023
#
# This script packs and unpacks 3D MRC files to JPEG stacks and vice versa.
# By default, JPEG packing uses 80% quality, which reduces the size to ~10%
# of the original while making minimal visual impact to cryoET tomograms.
# Warning: Only use this for visualization and annotation, not for
# downstream processing.
# Requirement: pip install mrcfile numpy
# Usage, single-file packing: ./jpeg_tomogram.py pack tomogram.mrc
# Usage, packing a folder of mrc files: ./jpeg_tomogram.py pack tomograms/
# Usage, single-file unpacking ./jpeg_tomogram.py unpack tomogram.jpgs
# Usage, unpacking a folder of jpgs files: ./jpeg_tomogram.py unpack tomograms/

import io
import os
import sys
import time
import shlex
import mrcfile
import argparse
import tempfile
import subprocess
import numpy as np
from PIL import Image
from pathlib import Path
from multiprocessing import Pool, cpu_count

# ANSI escape codes for colored text
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RESET = "\033[0m"

def print_warning(text):
    """Prints a warning message in yellow text"""
    print(f"{YELLOW}{text}{RESET}")

def print_error(text):
    """Prints an error message in red text"""
    print(f"{RED}{text}{RESET}", file=sys.stderr)

def print_success(text):
    """Prints a success message in green text"""
    print(f"{GREEN}{text}{RESET}")

def save_image(img_data, filename, quality):
    """Saves a single slice of the MRC data as a JPEG image"""
    with open(filename, 'wb') as f, io.BytesIO() as img_buffer:
        img_data.save(img_buffer, format='JPEG', quality=quality)
        img_data = img_buffer.getvalue()
        f.write(len(img_data).to_bytes(4, 'little'))
        f.write(img_data)

def load_image(filename):
    """Loads a single JPEG image"""
    with open(filename, 'rb') as f:
        img_size = int.from_bytes(f.read(4), 'little')
        img_data = f.read(img_size)
    with io.BytesIO(img_data) as img_buffer:
        img = Image.open(img_buffer)
        img.load()
    return img

def write_header(mrc, filename):
    """Writes the header information of the MRC file"""
    np.save(filename, mrc.header, allow_pickle=False)

def read_header(filename):
    """Reads the header information of the MRC file"""
    try:
        return np.load(filename)
    except FileNotFoundError:
        print_warning(f"Warning: Header file {filename} not found. Unpacked MRC file will have default header values.")
        return {}

def mrc_to_jpeg_stack(mrc_filename, jpeg_stack_filename, quality, cores=None, verbose=False):
    """Converts a MRC file into a stack of JPEG images"""
    if verbose:
        print(f"{jpeg_stack_filename}.jpgs is being packed...")
    if cores is None:
        cores = cpu_count()

    with mrcfile.open(mrc_filename, 'r') as mrc:
        data = mrc.data.astype(np.float32)  # ensure data is float type to prevent loss of precision
        mean = np.mean(data)
        std = np.std(data)
        data = (data - mean) / std  # normalize to zero mean and unit standard deviation
        data = data - np.min(data)
        data = data / np.max(data)
        data = (data * 255).astype(np.uint8)  # convert data to 8-bit integers

        write_header(mrc, jpeg_stack_filename + '_header.npy')  # write the header to a separate file

    jpeg_stack_filename = jpeg_stack_filename.rsplit('.', 1)[0] + f'.jpgs'  # add .jpgs to the filename

    with tempfile.TemporaryDirectory() as tmpdir:
        if cores > 1:
            with Pool(processes=cores) as pool:
                pool.starmap(save_image, [(Image.fromarray(slice), os.path.join(tmpdir, f'{i}.jpg'), quality) for i, slice in enumerate(data)])
        else:
            for i, slice in enumerate(data):
                save_image(Image.fromarray(slice), os.path.join(tmpdir, f'{i}.jpg'), quality)

        with open(jpeg_stack_filename, 'wb') as f:
            f.write(len(data).to_bytes(4, 'little'))
            for i in range(len(data)):
                with open(os.path.join(tmpdir, f'{i}.jpg'), 'rb') as img_file:
                    img_data = img_file.read()
                    f.write(len(img_data).to_bytes(4, 'little'))
                    f.write(img_data)
        print_success(f"{jpeg_stack_filename} successfully packed!")

def jpeg_stack_to_mrc(jpeg_stack_filename, mrc_filename, cores=None, verbose=False):
    """Converts a stack of JPEG images back into a MRC file"""
    if verbose:
        print(f"{mrc_filename}.mrc is being unpacked...")
    if cores is None:
        cores = cpu_count()

    quality = jpeg_stack_filename.split('_JPG')[-1].split('.')[0]  # extract quality from the filename
    mrc_filename = mrc_filename.rsplit('.', 1)[0] + f'.mrc'  # add .mrc to the filename
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(jpeg_stack_filename, 'rb') as f:
            num_images = int.from_bytes(f.read(4), 'little')

            for i in range(num_images):
                img_size = int.from_bytes(f.read(4), 'little')
                img_data = f.read(img_size)
                with open(os.path.join(tmpdir, f'{i}.jpg'), 'wb') as img_file:
                    img_file.write(img_data)

        images = []
        if cores > 1:
            with Pool(processes=cores) as pool:
                images = pool.map(load_image, [os.path.join(tmpdir, f'{i}.jpg') for i in range(num_images)])
        else:
            for i in range(num_images):
                images.append(load_image(os.path.join(tmpdir, f'{i}.jpg')))
        data = np.array([np.array(img) for img in images])

        header = read_header(os.path.splitext(jpeg_stack_filename)[0] + '_header.npy')

        with mrcfile.new(mrc_filename, overwrite=True) as mrc:
            include_fields = ['nx', 'ny', 'nz', 'mode', 'nxstart', 'nystart', 'nzstart', 'mx', 'my', 'mz', 'xlen', 'ylen', 'zlen', 'alpha', 'beta', 'gamma', 'mapc', 'mapr', 'maps', 'amin', 'amax', 'amean', 'ispg', 'extra', 'xorigin', 'yorigin', 'zorigin', 'map', 'machst', 'rms', 'nlabels', 'cella']  # 'nsymbt' has been removed because it can shift the unpacked mrc in x,y
            for field in include_fields:
                try:
                    mrc.header[field] = header[field]
                except:
                    pass
            mrc.set_data((data - 128).astype(np.int8))  # convert data to signed 8-bit integer
        print_success(f"{mrc_filename} successfully unpacked!")

def main():
    start_time = time.time()

    parser = argparse.ArgumentParser(description='Pack or unpack a JPEG stack.')
    parser.add_argument('mode', choices=['pack', 'unpack'], help='Whether to pack an MRC file into a JPEG stack or unpack a JPEG stack into an MRC file')
    parser.add_argument('input_path', help='The input file or directory')
    parser.add_argument('-o', '--output_path', help='The output file or directory (default: same as input path)')
    parser.add_argument('-e', '--external_viewer', help='External program to open the unpacked MRC file')
    parser.add_argument('-q', '--quality', type=int, default=80, help='The quality of the JPEG images in the stack (default: 80)')
    parser.add_argument('-c', '--cores', type=int, default=None, help='Number of CPU cores to use (default: all)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Print verbose output')
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path) if args.output_path else None
    if input_path.is_dir():
        if args.mode == 'pack':
            files = list(input_path.glob('*.mrc')) + list(input_path.glob('*.rec'))
            if not files:
                print_error(f"Error: No .mrc or .rec files found in {input_path}")
                sys.exit(1)
        elif args.mode == 'unpack':
            files = list(input_path.glob('*.jpgs'))
            if not files:
                print_error(f"Error: No .jpgs files found in {input_path}")
                sys.exit(1)
        if output_path and not output_path.is_dir():
            print_error(f"Error: Output path {output_path} is not a directory")
            sys.exit(1)
        output_path = output_path or input_path
        num_files = len(files)
        cores = args.cores if args.cores else cpu_count()
        min_cores = min(cores, num_files)
        if args.mode == 'pack':
            print(f"Packing {num_files} tomograms with JPEG{args.quality} across {min_cores} CPU cores...")
            with Pool(processes=cores) as pool:
                pool.starmap(mrc_to_jpeg_stack, [(str(f), str(output_path / (f.stem + f'_JPG{args.quality}')), args.quality, 1, args.verbose) for f in files])  # add JPEG quality to the filename
        elif args.mode == 'unpack':
            print(f"Unpacking {num_files} tomograms across {min_cores} CPU cores...")
            with Pool(processes=cores) as pool:
                pool.starmap(jpeg_stack_to_mrc, [(str(f), str(output_path / (f.stem.replace(f'_JPG{args.quality}', f'_fromJPG{args.quality}'))), 1, args.verbose) for f in files])  # add JPEG quality to the filename
            if args.external_viewer:
                print(f"Opening {num_files} files with {args.external_viewer}...")
                file_names = [str(file).replace('.jpgs', '.mrc') for file in files]
                subprocess.run([args.external_viewer] + shlex.split(' '.join(file_names)), check=True)

    else:
        if args.output_path is None:
            if args.mode == 'pack':
                args.output_path = args.input_path.rsplit('.', 1)[0] + f'_JPG{args.quality}'  # add JPEG quality to the filename
            elif args.mode == 'unpack':
                args.output_path = args.input_path.rsplit('.', 1)[0]
        if args.mode == 'pack':
            mrc_to_jpeg_stack(args.input_path, args.output_path, args.quality, args.cores, args.verbose)
        elif args.mode == 'unpack':
            jpeg_stack_to_mrc(args.input_path, args.output_path, args.cores, args.verbose)
            if args.external_viewer:
                print(f"Opening {args.output_path}'.mrc' with {args.external_viewer}...")
                subprocess.run([args.external_viewer, args.output_path + f'.mrc'], check=True)
        num_files = 1

    end_time = time.time()
    print(f"Total time taken to process {num_files} tomograms: {end_time - start_time:.2f} seconds")

if __name__ == '__main__':
    main()
