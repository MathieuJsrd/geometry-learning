import unittest
import tensorflow as tf
import numpy as np

from topoml_util.test_files import gmm_output
from topoml_util.GaussianMixtureLoss import GaussianMixtureLoss

sess = tf.InteractiveSession()
DATA_FILE = '../files/geodata_vectorized.npz'


class TestGaussianMixtureLoss(unittest.TestCase):
    def test_bivariate_gaussian_loss(self):
        true = np.array([gmm_output.target])
        pred = np.array([gmm_output.prediction])
        loss = GaussianMixtureLoss(num_components=5, num_points=14).geom_gaussian_mixture_loss(true, pred)
        print(loss.eval())

    def test_single_gaussian_loss(self):
        true = np.array([
            [1., 1., 0.],
            [1., 1., 0.],
            [1., 1., 0.],
            [1., 1., 0.],
        ])
        pred1 = np.array([
            [1., 1., 0.],
            [1., 1., 0.],
            [1., 1., 0.],
            [1., 1., 0.],
        ])
        pred2 = np.array([
            [0., 0., 0.],
            [0., 0., 0.],
            [0., 0., 0.],
            [0., 0., 0.],
        ])
        loss1 = GaussianMixtureLoss(num_components=1, num_points=1).univariate_gmm_loss(true, pred1)
        loss2 = GaussianMixtureLoss(num_components=1, num_points=1).univariate_gmm_loss(true, pred2)
        self.assertLess(loss1.eval(), loss2.eval())

