"""
This script executes the task of estimating the building type, based solely on the geometry for that building.
The data for this script can be generated by running the prep/get-data.sh and prep/preprocess-buildings.py scripts,
which will take about an hour or two.
"""
import os
import socket
import sys
from datetime import datetime, timedelta
from time import time

import numpy as np
from keras import Input
from keras.callbacks import TensorBoard, EarlyStopping
from keras.engine import Model
from keras.layers import Dense, Flatten, Dropout
from keras.optimizers import Adam
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

from topoml_util import geom_scaler
from topoml_util.slack_send import notify

SCRIPT_VERSION = '1.0.2'
SCRIPT_NAME = os.path.basename(__file__)
TIMESTAMP = str(datetime.now()).replace(':', '.')
SIGNATURE = SCRIPT_NAME + ' ' + SCRIPT_VERSION + ' ' + TIMESTAMP
DATA_FOLDER = '../files/buildings/'
FILENAME_PREFIX = 'buildings_order_30_train'
SCRIPT_START = time()

# Hyperparameters
hp = {
    'BATCH_SIZE': int(os.getenv('BATCH_SIZE', 512)),
    'TRAIN_VALIDATE_SPLIT': float(os.getenv('TRAIN_VALIDATE_SPLIT', 0.1)),
    'REPEAT_DEEP_ARCH': int(os.getenv('REPEAT_DEEP_ARCH', 0)),
    'DENSE_SIZE': int(os.getenv('DENSE_SIZE', 32)),
    'EPOCHS': int(os.getenv('EPOCHS', 200)),
    'LEARNING_RATE': float(os.getenv('LEARNING_RATE', 1e-4)),
    'PATIENCE': int(os.getenv('PATIENCE', 16)),
    'DROPOUT': float(os.getenv('DROPOUT', 0.5)),
    'GEOM_SCALE': float(os.getenv("GEOM_SCALE", 0)),  # If no default or 0: overridden when data is known
    'EARLY_STOPPING': bool(os.getenv('EARLY_STOPPING', False)),
}
OPTIMIZER = Adam(lr=hp['LEARNING_RATE'], clipnorm=1.)

# Load training data
train_geoms = []
train_labels = []

for file in os.listdir(DATA_FOLDER):
    if file.startswith(FILENAME_PREFIX) and file.endswith('.npz'):
        train_loaded = np.load(DATA_FOLDER + file)
        if len(train_geoms):
            train_geoms = np.append(train_geoms, train_loaded['geoms'], axis=0)
            train_labels = np.append(train_labels, train_loaded['building_type'], axis=0)
        else:
            train_geoms = train_loaded['geoms']
            train_labels = train_loaded['building_type']

# Determine final test mode or standard
if len(sys.argv) > 1 and sys.argv[1] in ['-t', '--test']:
    print('Training in final test mode')
    TEST_DATA_FILE = '../files/buildings/buildings_order_30_test.npz'
    test_loaded = np.load(TEST_DATA_FILE)
    test_geoms = test_loaded['geoms']
    test_labels = test_loaded['building_type']
else:
    print('Training in standard training mode')
    # Split the training data in random seen/unseen sets
    train_geoms, test_geoms, train_labels, test_labels = train_test_split(train_geoms, train_labels, test_size=0.1)

# Normalize
geom_scale = hp['GEOM_SCALE'] or geom_scaler.scale(train_geoms)
train_geoms = geom_scaler.transform(train_geoms, geom_scale)
test_geoms = geom_scaler.transform(test_geoms, geom_scale)  # re-use scale from training

# Map building types to one-hot vectors
train_targets = np.zeros((len(train_labels), train_labels.max() + 1))
for index, building_type in enumerate(train_labels):
    train_targets[index, building_type] = 1

# Shape determination
geom_max_points, geom_vector_len = train_geoms.shape[1:]
output_size = train_targets.shape[-1]

# Build model
inputs = Input(shape=(geom_max_points, geom_vector_len))
model = Flatten()(inputs)
model = Dense(hp['DENSE_SIZE'], activation='relu')(model)
model = Dropout(hp['DROPOUT'])(model)

for _ in range(hp['REPEAT_DEEP_ARCH']):
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
if hp['EARLY_STOPPING']:
    callbacks.append(EarlyStopping(patience=hp['PATIENCE'], min_delta=0.001))

history = model.fit(
    x=train_geoms,
    y=train_targets,
    epochs=hp['EPOCHS'],
    batch_size=hp['BATCH_SIZE'],
    validation_split=hp['TRAIN_VALIDATE_SPLIT'],
    callbacks=callbacks).history

# Run on unseen test data
test_pred = [np.argmax(prediction) for prediction in model.predict(test_geoms)]
accuracy = accuracy_score(test_labels, test_pred)

runtime = time() - SCRIPT_START
message = 'on {} completed with accuracy of \n{:f} \nin {} in {} epochs\n'.format(
    socket.gethostname(), accuracy, timedelta(seconds=runtime), len(history['val_loss']))

for key, value in sorted(hp.items()):
    message += '{}: {}\t'.format(key, value)

notify(SIGNATURE, message)
print(SCRIPT_NAME, 'finished successfully with', message)
