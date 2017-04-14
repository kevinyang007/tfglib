# Created by Albert Aparicio on 21/10/16
# coding: utf-8

# This import makes Python use 'print' as in Python 3.x
from __future__ import print_function

from os.path import join as path_join

import h5py
import numpy as np
from keras.utils.np_utils import to_categorical

from tfglib.construct_table import parse_file
from tfglib.seq2seq_normalize import mask_data
from tfglib.utils import kronecker_delta
from tfglib.zero_pad import zero_pad_params


class Seq2SeqDatatable(object):
  def __init__(self, data_dir, datatable_file, speakers_file='speakers.list',
               basenames_file='seq2seq_basenames.list', shortseq=False,
               max_seq_length=None):
    """Make sure that if we are going to split sequences into short parts, there
    is an int max_seq_length.
  
    If we are not, then, max_seq_length will be computed from the dataset"""
    try:
      assert (shortseq is True and type(max_seq_length) == int) or (
        shortseq is False)
    except AssertionError:
      print(
          "If you are going to use split sequences, please set the "
          "'max_seq_length' parameter as an integer value")

    # Make sure the data output filename is a string
    try:
      assert type(datatable_file) == str
    except AssertionError:
      print("Please, make sure the data output filename is a string")

    self.data_dir = data_dir
    self.datatable_file = datatable_file

    # Parse speakers file
    speakers = open(path_join(data_dir, speakers_file), 'r').readlines()
    # Strip '\n' characters
    self.speakers = [line.split('\n')[0] for line in speakers]

    # Parse basenames file
    # This file should be equal for all speakers
    basenames = open(path_join(data_dir, basenames_file), 'r').readlines()
    # Strip '\n' characters
    self.basenames = [line.split('\n')[0] for line in basenames]

    if shortseq:
      self.max_seq_length = max_seq_length
    else:
      # Find number of frames in longest sequence in the dataset
      self.max_seq_length = self.find_longest_sequence(self.speakers,
                                                       self.basenames)

  def find_longest_sequence(self, speakers_list, basenames_list):
    """Find the number of speech frames from the longest sequence
    among all speakers
  
    # Arguments
        data_dir: directory of data to be used in the datatable.
        speakers_list: list of speakers to be used
        basenames_list: list of filenames to be used
  
    # Returns
        An integer with the number of frames of the longest sequence"""

    longest_sequence = 0

    for speaker in speakers_list:
      for basename in basenames_list:
        params = parse_file(
            1,
            path_join(
                self.data_dir,
                'vocoded_s2s',
                speaker,
                basename + '.' + 'lf0' + '.dat'
                )
            )

        if params.shape[0] > longest_sequence:
          longest_sequence = params.shape[0]

    return longest_sequence

  def seq2seq_build_file_table(self, source_dir, src_index, target_dir,
                               trg_index, basename):
    """Build a datatable from the vocoded parameters of a sequence
    from a source-target pair of speakers
  
    # Arguments
        source_dir: directory path to the source files
        src_index: index (0-9) of the source speaker in the speakers list
        target_dir: directory path to the target files
        trg_index: index (0-9) of the target speaker in the speakers list
        basename: name without extension of the file's params to be prepared
        longest_seq: number of frames of the longest sequence in the database
  
    # Returns
        - Zero-padded (by frames) source and target datatables
        - Source and target mask vectors indicating which frames are padded (0)
          and which of them are original from the data (1)
  
        The mask vectors are to be used in Keras' fit method"""

    # Parse parameter files
    source_mcp = parse_file(40, path_join(
        source_dir, basename + '.' + 'mcp' + '.dat'
        ))

    source_f0 = parse_file(1, path_join(
        source_dir, basename + '.' + 'lf0' + '.dat'
        ))
    source_f0_i = parse_file(1, path_join(
        source_dir, basename + '.' + 'lf0' + '.i.dat'
        ))  # Interpolated data

    source_vf = parse_file(1, path_join(
        source_dir, basename + '.' + 'vf' + '.dat'
        ))
    source_vf_i = parse_file(1, path_join(
        source_dir, basename + '.' + 'vf' + '.i.dat'
        ))  # Use interpolated data

    target_mcp = parse_file(40, path_join(
        target_dir, basename + '.' + 'mcp' + '.dat'
        ))
    target_f0 = parse_file(1, path_join(
        target_dir, basename + '.' + 'lf0' + '.dat'
        ))
    target_f0_i = parse_file(1, path_join(
        target_dir, basename + '.' + 'lf0' + '.i.dat'
        ))  # Interpolated data

    target_vf = parse_file(1, path_join(
        target_dir, basename + '.' + 'vf' + '.dat'
        ))
    target_vf_i = parse_file(1, path_join(
        target_dir, basename + '.' + 'vf' + '.i.dat'
        ))  # Use interpolated data

    # Build voiced/unvoiced flag arrays
    # The flags are:
    #   1 -> voiced
    #   0 -> unvoiced
    assert source_vf.shape == source_f0.shape
    source_voiced = np.empty(source_vf.shape)
    for index, vf in enumerate(source_vf):
      source_voiced[index] = 1 - kronecker_delta(source_vf[index])

    assert target_vf.shape == target_f0.shape
    target_voiced = np.empty(target_vf.shape)
    for index, vf in enumerate(target_vf):
      target_voiced[index] = 1 - kronecker_delta(target_vf[index])

    # Initialize End-Of-Sequence flag
    src_eos_flag = np.zeros(source_vf.shape)
    src_eos_flag[-1, :] = 1

    trg_eos_flag = np.zeros(target_vf.shape)
    trg_eos_flag[-1, :] = 1

    # Initialize one-hot-encoded speaker indexes
    src_spk_index = to_categorical(
        src_index * np.ones((source_vf.shape[0],), dtype=int), 10)
    trg_spk_index = to_categorical(
        trg_index * np.ones((target_vf.shape[0],), dtype=int), 10)

    # Initialize padding masks, to be passed into keras' fit
    # Source mask
    source_mask = np.concatenate((
      np.zeros((
        self.max_seq_length - source_mcp.shape[0],
        1
        )),
      np.ones((
        source_mcp.shape[0],
        1
        ))
      ))

    # Target mask
    target_mask = np.concatenate((
      np.ones((
        target_mcp.shape[0],
        1
        )),
      np.zeros((
        self.max_seq_length - target_mcp.shape[0],
        1
        ))
      ))

    assert source_mask.shape == target_mask.shape

    # Concatenate zero-padded source and target params
    source_params = np.concatenate((
      zero_pad_params(self.max_seq_length, 'src', source_mcp),
      zero_pad_params(self.max_seq_length, 'src', source_f0_i),
      zero_pad_params(self.max_seq_length, 'src', source_vf_i),
      zero_pad_params(self.max_seq_length, 'src', source_voiced),
      zero_pad_params(self.max_seq_length, 'src', src_eos_flag),
      zero_pad_params(self.max_seq_length, 'src', src_spk_index),
      zero_pad_params(self.max_seq_length, 'src', trg_spk_index)
      ), axis=1)

    target_params = np.concatenate((
      zero_pad_params(self.max_seq_length, 'trg', target_mcp),
      zero_pad_params(self.max_seq_length, 'trg', target_f0_i),
      zero_pad_params(self.max_seq_length, 'trg', target_vf_i),
      zero_pad_params(self.max_seq_length, 'trg', target_voiced),
      zero_pad_params(self.max_seq_length, 'trg', trg_eos_flag)
      ), axis=1)

    return source_params, source_mask, target_params, target_mask

  def seq2seq_construct_datatable(self):
    """Concatenate and zero-pad all vocoder parameters
    from all files in basenames_file, for all speakers in speakers_file
  
    # Arguments
        data_dir: directory of data to be used in the datatable.
        speakers_file: file with the list of speakers to be used
        basenames_file: file with the list of filenames to be used
  
    # Returns
        - Concatenated and zero-padded (by frames) source and target datatables
        - Source and target mask matrices indicating which frames
          are padded (0) and which of them are original from the data (1)"""

    # Initialize datatables
    src_datatable = []
    trg_datatable = []
    src_masks = []
    trg_masks = []

    # Initialize maximum and minimum values matrices
    spk_max = np.zeros((10, 42))
    spk_min = 1e+50 * np.ones((10, 42))

    # Nest iterate over speakers
    for src_index, src_spk in enumerate(self.speakers):
      for trg_index, trg_spk in enumerate(self.speakers):
        for basename in self.basenames:
          print(src_spk + '->' + trg_spk + ' ' + basename)

          (aux_src_params,
           aux_src_mask,
           aux_trg_params,
           aux_trg_mask
           ) = self.seq2seq_build_file_table(
              path_join(self.data_dir, 'vocoded_s2s', src_spk),
              src_index,
              path_join(self.data_dir, 'vocoded_s2s', trg_spk),
              trg_index,
              basename,
              )

          # Obtain maximum and minimum values of each speaker's parameter
          # Mask parameters to avoid the zero-padded values
          masked_params = mask_data(aux_src_params[:, 0:42], aux_src_mask)

          # Compute maximum and minimum values
          spk_max[src_index, :] = np.maximum(
              spk_max[src_index, :], np.ma.max(masked_params, axis=0)
              )
          spk_min[src_index, :] = np.minimum(
              spk_min[src_index, :], np.ma.min(masked_params, axis=0)
              )

          # Append sequence params and masks to main datatables and masks
          src_datatable.append(aux_src_params)
          trg_datatable.append(aux_trg_params)
          src_masks.append(aux_src_mask)
          trg_masks.append(aux_trg_mask)

    return (np.array(src_datatable),
            np.array(src_masks).reshape(-1, self.max_seq_length),
            # Reshape to 2D mask
            np.array(trg_datatable),
            np.array(trg_masks).reshape(-1, self.max_seq_length),
            # Reshape 2D mask
            # max_seq_length,
            spk_max,
            spk_min)

  def seq2seq_save_datatable(self):
    """Generate datatables and masks and save them to .h5 file
  
    # Arguments
        data_dir: directory of data to be used for the datatable.
        datatable_out_file: path to the output .h5 file (no extension)
  
    # Returns
        An h5py file with source and target datatables and matrices.
  
        It also returns the data returned by seq2seq_construct_datatable:
        - Concatenated and zero-padded (by frames) source and target datatables
        - Source and target mask matrices indicating which frames
          are padded (0) and which of them are original from the data (1)"""

    # Construct datatables and masks
    (source_datatable,
     source_masks,
     target_datatable,
     target_masks,
     speakers_max,
     speakers_min) = self.seq2seq_construct_datatable()

    # Save dataset names and dataset arrays for elegant iteration when saving
    data_dict = {
      'src_datatable': source_datatable,
      'trg_datatable': target_datatable,
      'src_mask'     : source_masks,
      'trg_mask'     : target_masks
      }

    # Save data to .h5 file
    with h5py.File(self.datatable_file + '.h5', 'w') as f:
      # Save max_seq_length as an attribute
      f.attrs.create('max_seq_length', self.max_seq_length, dtype=int)
      f.attrs.create('speakers_max', speakers_max)
      f.attrs.create('speakers_min', speakers_min)

      # Save the rest of datasets
      for dataset_name, dataset in data_dict.items():
        f.create_dataset(
            dataset_name,
            data=dataset,
            compression="gzip",
            compression_opts=9
            )

      f.close()

    return (source_datatable,
            source_masks,
            target_datatable,
            target_masks,
            speakers_max,
            speakers_min)

  def seq2seq2_load_datatable(self):
    """Load datasets and masks from an h5py file
  
    # Arguments
        datatable_file: path to the .h5 file that contains the data
  
    # Returns
        The same data returned by seq2seq_construct_datatable:
  
        - Concatenated and zero-padded (by frames) source and target datatables
        - Source and target mask matrices indicating which frames
          are padded (0) and which of them are original from the data (1)"""

    # Load data from .h5 file
    with h5py.File(self.datatable_file, 'r') as file:
      # Load datasets
      source_datatable = file['src_datatable'][:, :]
      target_datatable = file['trg_datatable'][:, :]

      source_masks = file['src_mask'][:, :]
      target_masks = file['trg_mask'][:, :]

      # Load max_seq_length attribute
      self.max_seq_length = file.attrs.get('max_seq_length')
      speakers_max = file.attrs.get('speakers_max')
      speakers_min = file.attrs.get('speakers_min')

      file.close()

    return (source_datatable,
            source_masks,
            target_datatable,
            target_masks,
            speakers_max,
            speakers_min)
