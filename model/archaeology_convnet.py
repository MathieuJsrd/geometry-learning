"""
This script executes the task of estimating the type of an archaeological feature, based solely on the geometry for
that feature. The data for this script can be found at http://hdl.handle.net/10411/GYPPBR.
"""

import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import time
from urllib.request import urlretrieve

import numpy as np
from keras import Input
from keras.callbacks import TensorBoard
from keras.engine import Model
from keras.layers import Dense, Conv1D, MaxPooling1D, GlobalAveragePooling1D, Dropout
from keras.optimizers import Adam
from keras.preprocessing.sequence import pad_sequences
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(os.path.join(SCRIPT_DIR, PACKAGE_PARENT)))

from prep.ProgressBar import ProgressBar
from topoml_util import geom_scaler
from topoml_util.slack_send import notify

SCRIPT_VERSION = '2.0.5'
SCRIPT_NAME = os.path.basename(__file__)
TIMESTAMP = str(datetime.now()).replace(':', '.')
SIGNATURE = SCRIPT_NAME + ' ' + SCRIPT_VERSION + ' ' + TIMESTAMP
DATA_FOLDER = '../files/archaeology/'
TRAIN_DATA_FILE = 'archaeology_train_v7.npz'
TEST_DATA_FILE = 'archaeology_test_v7.npz'
TRAIN_DATA_URL = 'https://dataverse.nl/api/access/datafile/11377'
TEST_DATA_URL = 'https://dataverse.nl/api/access/datafile/11376'
SCRIPT_START = time()

# Hyperparameters
hp = {
    'BATCH_SIZE': int(os.getenv('BATCH_SIZE', 32)),
    'TRAIN_VALIDATE_SPLIT': float(os.getenv('TRAIN_VALIDATE_SPLIT', 0.1)),
    'REPEAT_DEEP_ARCH': int(os.getenv('REPEAT_DEEP_ARCH', 0)),
    'DENSE_SIZE': int(os.getenv('DENSE_SIZE', 32)),
    'EPOCHS': int(os.getenv('EPOCHS', 200)),
    'LEARNING_RATE': float(os.getenv('LEARNING_RATE', 1e-4)),
    'DROPOUT': float(os.getenv('DROPOUT', 0.0)),
    'GEOM_SCALE': float(os.getenv("GEOM_SCALE", 0)),  # If no default or 0: overridden when data is known
}
OPTIMIZER = Adam(lr=hp['LEARNING_RATE'])

# Load training data
path = Path(DATA_FOLDER + TRAIN_DATA_FILE)
if not path.exists():
    print("Retrieving training data from web...")
    urlretrieve(TRAIN_DATA_URL, DATA_FOLDER + TRAIN_DATA_FILE)

train_loaded = np.load(DATA_FOLDER + TRAIN_DATA_FILE)
train_geoms = train_loaded['geoms']
train_labels = train_loaded['feature_type']

# Determine final test mode or standard
if len(sys.argv) > 1 and sys.argv[1] in ['-t', '--test']:
    print('Training in final test mode')
    path = Path(DATA_FOLDER + TEST_DATA_FILE)
    if not path.exists():
        print("Retrieving test data from web...")
        urlretrieve(TEST_DATA_URL, DATA_FOLDER + TEST_DATA_FILE)

    test_loaded = np.load(DATA_FOLDER + TEST_DATA_FILE)
    test_geoms = test_loaded['geoms']
    test_labels = test_loaded['feature_type']
else:
    print('Training in standard training mode')
    # Split the training data in random seen/unseen sets
    train_geoms, test_geoms, train_labels, test_labels = train_test_split(train_geoms, train_labels, test_size=0.1)

# Normalize
geom_scale = hp['GEOM_SCALE'] or geom_scaler.scale(train_geoms)
train_geoms = geom_scaler.transform(train_geoms, geom_scale)
test_geoms = geom_scaler.transform(test_geoms, geom_scale)  # re-use variance from training

# Sort data according to sequence length
zipped = zip(train_geoms, train_labels)
train_input_sorted = {}
train_labels_sorted = {}
for geom, label in sorted(zipped, key=lambda x: len(x[0]), reverse=True):
    # Map types to one-hot vectors
    # noinspection PyUnresolvedReferences
    one_hot_label = np.zeros((np.array(train_labels).max() + 1))
    one_hot_label[label] = 1

    sequence_len = geom.shape[0]
    smallest_size_subset = sorted(train_input_sorted.keys())[0] if train_input_sorted else None

    if not smallest_size_subset:  # This is the first data point
        train_input_sorted[sequence_len] = [geom]
        train_labels_sorted[sequence_len] = [one_hot_label]
        continue

    if sequence_len in train_input_sorted:  # the entry exists, append
        train_input_sorted[sequence_len].append(geom)
        train_labels_sorted[sequence_len].append(one_hot_label)
        continue

    # the size subset does not exist yet
    # append the data to the smallest size subset if it isn't batch-sized yet
    if len(train_input_sorted[smallest_size_subset]) < hp['BATCH_SIZE']:
        geom = pad_sequences([geom], smallest_size_subset)[0]  # make it the same size as the rest in the subset
        train_input_sorted[smallest_size_subset].append(geom)
        train_labels_sorted[smallest_size_subset].append(one_hot_label)
    else:
        train_input_sorted[sequence_len] = [geom]
        train_labels_sorted[sequence_len] = [one_hot_label]

# Shape determination
geom_vector_len = train_geoms[0].shape[1]
output_size = np.array(train_labels).max() + 1

# Build model
inputs = Input(shape=(None, geom_vector_len))
model = Conv1D(32, (5,), activation='relu', padding='SAME')(inputs)
# model = Conv1D(32, (5,), activation='relu', padding='SAME')(model)
model = MaxPooling1D(3)(model)
model = Conv1D(64, (5,), activation='relu', padding='SAME')(model)
model = GlobalAveragePooling1D()(model)
model = Dense(hp['DENSE_SIZE'], activation='relu')(model)
model = Dropout(hp['DROPOUT'])(model)
model = Dense(output_size, activation='softmax')(model)

model = Model(inputs=inputs, outputs=model)
model.compile(
    loss='categorical_crossentropy',
    metrics=['accuracy'],
    optimizer=OPTIMIZER),
model.summary()

# Callbacks
callbacks = [TensorBoard(log_dir='./tensorboard_log/' + SIGNATURE, write_graph=False)]

pgb = ProgressBar()
for epoch in range(hp['EPOCHS']):
    for sequence_len in sorted(train_input_sorted.keys()):
        message = 'Epoch {} of {}, sequence length {}'.format(epoch + 1, hp['EPOCHS'], sequence_len)
        pgb.update_progress(epoch/hp['EPOCHS'], message)

        inputs = np.array(train_input_sorted[sequence_len])
        labels = np.array(train_labels_sorted[sequence_len])

        model.fit(
            x=inputs,
            y=labels,
            verbose=0,
            epochs=epoch + 1,
            initial_epoch=epoch,
            batch_size=hp['BATCH_SIZE'],
            validation_split=hp['TRAIN_VALIDATE_SPLIT'],
            callbacks=callbacks)

# Run on unseen test data
print('\n\nRun on test data...')
test_preds = [model.predict(np.array([test])) for test in test_geoms]
test_preds = [np.argmax(pred) for pred in test_preds]
accuracy = accuracy_score(test_labels, test_preds)

runtime = time() - SCRIPT_START
message = 'on {} completed with accuracy of \n{:f} \nin {} in {} epochs\n'.format(
    socket.gethostname(), accuracy, timedelta(seconds=runtime), hp['EPOCHS'])

for key, value in sorted(hp.items()):
    message += '{}: {}\t'.format(key, value)

notify(SIGNATURE, message)
print(SCRIPT_NAME, 'finished successfully with', message)
