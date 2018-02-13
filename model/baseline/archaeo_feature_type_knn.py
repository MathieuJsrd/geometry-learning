"""
This script executes the task of estimating the type of an archaeological feature, based solely on the geometry for
that feature. The data for this script can be regenerated by running the prep/get-data.sh and
prep/preprocess-archaeology.py scripts, which will take about an hour or two.

This script itself will run for about four hours depending on your hardware, if you have at least a recent i7 or
comparable.
"""

import multiprocessing
import os
from time import time
from datetime import datetime, timedelta

import numpy as np
import sys

from sklearn.metrics import accuracy_score
from sklearn.model_selection import cross_val_score, StratifiedShuffleSplit, GridSearchCV
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(os.path.join(SCRIPT_DIR, PACKAGE_PARENT)))

from topoml_util.slack_send import notify

SCRIPT_VERSION = '0.0.4'
SCRIPT_NAME = os.path.basename(__file__)
TIMESTAMP = str(datetime.now()).replace(':', '.')
TRAINING_DATA_FILE = '../../files/archaeology/archaeo_features_train.npz'
NUM_CPUS = multiprocessing.cpu_count() - 1 or 1
SCRIPT_START = time()

if __name__ == '__main__':  # this is to squelch warnings on scikit-learn multithreaded grid search
    train_loaded = np.load(TRAINING_DATA_FILE)
    train_fourier_descriptors = train_loaded['fourier_descriptors']
    train_feature_type = train_loaded['feature_type']

    scaler = StandardScaler().fit(train_fourier_descriptors)
    train_fourier_descriptors = scaler.transform(train_fourier_descriptors)
    k_range = np.linspace(start=1, stop=16, num=16, dtype=int)
    param_grid = dict(n_neighbors=k_range)
    cv = StratifiedShuffleSplit(n_splits=5, test_size=0.2, random_state=42)
    grid = GridSearchCV(
        KNeighborsClassifier(),
        n_jobs=NUM_CPUS,
        param_grid=param_grid,
        verbose=10,
        cv=cv)

    print('Performing grid search on model...')
    print('Using %i threads for grid search' % NUM_CPUS)
    grid.fit(train_fourier_descriptors, train_feature_type)

    print("The best parameters are %s with a score of %0.3f"
          % (grid.best_params_, grid.best_score_))

    print('Training model on best parameters...')
    clf = KNeighborsClassifier(n_neighbors=grid.best_params_['n_neighbors'])
    scores = cross_val_score(clf, train_fourier_descriptors, train_feature_type, cv=10, n_jobs=NUM_CPUS)
    print('Cross-validation scores:', scores)
    clf.fit(train_fourier_descriptors, train_feature_type)

    # Run predictions on unseen test data to verify generalization
    TEST_DATA_FILE = '../../files/archaeology/archaeo_features_test.npz'
    test_loaded = np.load(TEST_DATA_FILE)
    test_fourier_descriptors = test_loaded['fourier_descriptors']
    test_feature_type = np.asarray(test_loaded['feature_type'], dtype=int)
    test_fourier_descriptors = scaler.transform(test_fourier_descriptors)

    print('Run on test data...')
    predictions = clf.predict(test_fourier_descriptors)
    accuracy = accuracy_score(test_feature_type, predictions)
    print('Test accuracy: %0.3f' % accuracy)

    runtime = time() - SCRIPT_START
    message = 'test accuracy of {0} in {1}'.format(str(accuracy), timedelta(seconds=runtime))
    notify(SCRIPT_NAME, message)
    print(SCRIPT_NAME, 'finished successfully in {}'.format(timedelta(seconds=runtime)))
