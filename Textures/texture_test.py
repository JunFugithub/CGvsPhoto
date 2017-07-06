import sys
sys.path.append('../CGvsPhoto')

import image_loader as il 
from dsift import DsiftExtractor

# import pandas as pd
import matplotlib.pyplot as plt

import numpy as np


# from sklearn.neural_network import MLPClassifier
from sklearn.svm import LinearSVC
from sklearn.metrics import accuracy_score
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture

from multiprocessing import Pool

from functools import partial

import pickle


def dump_model(model, path): 
	pickle.dump(model, open(path, 'wb'))

def load_model(path):
	return(pickle.load(open(path, 'rb')))

def compute_fisher(X, gmm, alpha = 0.5): 

	weights = gmm.weights_
	means = gmm.means_
	covars = gmm.covariances_

	K = weights.shape[0]
	N = X.shape[0]
	F = X.shape[1]
	T = X.shape[2]

	G = np.empty([N, 2*F*K])
	gamma = np.empty([N,K,T])
	for t in range(T):
		gamma[:,:,t] = gmm.predict_proba(X[:,:,t])

	for i in range(K):

		shifted_X = (X - np.reshape(means[i],[1,F,1]))/np.reshape(covars[i], [1,F,1])

		G_mu = np.sum(shifted_X*gamma[:,i:i+1, :]/(T*np.sqrt(weights[i])), axis = 2)
		G_sig = np.sum(gamma[:,i:i+1, :]*(shifted_X**2 - 1)/(T*np.sqrt(2*weights[i])), axis = 2)

		G[:, 2*i*F:2*(i+1)*F] = np.concatenate([G_mu, G_sig], axis = 1)

	# del(G_mu, G_sig, shifted_X, gamma)
	# Power normalization 
	G = np.sign(G)*np.power(np.abs(G), alpha)

	# L2 normalization
	G = G/np.reshape(np.sqrt(np.sum(G**2, axis = 1)), [N,1])

	return(G)


def compute_features(data, i, batch_size, nb_mini_patch, 
					 nb_batch,  only_green = False):

	extractor1 = DsiftExtractor(8,16,1)
	extractor2 = DsiftExtractor(16,32,1)

	print('Compute features for batch ' + str(i+1) + '/' + str(nb_batch))
	images, labels = data[0], data[1]

	features = []
	y_train = []
	for j in range(batch_size):
		img = (images[j]*256).astype(np.uint8)
		if not only_green:
			img = np.dot(img, [0.299, 0.587, 0.114])
		feaArr1,positions = extractor1.process_image(img, verbose = False)
		feaArr2,positions = extractor2.process_image(img, verbose = False)
		features.append(np.concatenate([feaArr1, feaArr2]).reshape([128, nb_mini_patch]))
		y_train.append(labels[j,0])

	return(features, y_train)



class Texture_model: 

	def __init__(self, data_directory, model_directory, image_size, 
				 keep_PCA = 64, K_gmm = 64, only_green = False): 


		self.model_name = input("   Choose a name for the model : ")
		self.model_directory = model_directory

		# Initialize hyper-parameters
		self.image_size = image_size
		self.keep_PCA = keep_PCA
		self.K_gmm = K_gmm
		self.only_green = only_green
		self.nb_mini_patch = int(image_size/8 - 1)**2 + int(image_size/16 - 1)**2 


		# Initialize database
		self.data = il.Database_loader(directory = data_directory, 
							  		   size = image_size, 
							  		   only_green = only_green)





		# Initialize classifiers
		self.PCAs = []
		for i in range(self.nb_mini_patch):
			self.PCAs.append(PCA(n_components=keep_PCA))

		self.gmm = GaussianMixture(n_components=K_gmm, 
								   covariance_type='diag')
		self.clf_svm = LinearSVC()



	def train(self, nb_train_batch, batch_size = 50): 

		features = np.empty([nb_train_batch*batch_size, 128, self.nb_mini_patch])
		y_train = np.empty([nb_train_batch*batch_size, ])
		print('Training...')

		data_train = []
		for i in range(nb_train_batch):
			print('Getting batch ' + str(i+1) + '/' + str(nb_train_batch))
			images_batch, y_batch = self.data.get_next_train_batch(batch_size = batch_size,
													   		  crop = False)
			data_train.append([images_batch, y_batch])

		pool = Pool()  

		to_compute = [i for i in range(nb_train_batch)]
		result = pool.starmap(partial(compute_features, 
								  batch_size = batch_size, 
								  nb_mini_patch = self.nb_mini_patch, 
								  nb_batch = nb_train_batch,
								  only_green = self.only_green),
								  zip(data_train, to_compute)) 

		del(data_train)

		index = 0
		for i in range(len(result)):
			features[index:index+batch_size] = result[i][0]
			y_train[index:index+batch_size] = result[i][1]

			index+=batch_size


		del(result)
		# print(y_train)

		
		# for i in range(nb_mini_patch):
		# 	# normalize(features[:,:,i])

		for i in range(self.nb_mini_patch):
			print('Fitting PCAs ' + str(i+1) + '/' + str(self.nb_mini_patch))
			self.PCAs[i].fit(features[:,:,i])

		# pca.fit(np.concatenate([features[:,:,i] for i in range(nb_mini_patch)]))

		print('Dimension reduction...')
		features_PCA = np.empty([nb_train_batch*batch_size, self.keep_PCA, self.nb_mini_patch])
		for i in range(self.nb_mini_patch):
			# features_PCA[:,:,i] = pca.transform(features[:,:,i])
			features_PCA[:,:,i] = self.PCAs[i].transform(features[:,:,i])

		del(features)

		print('Fitting Gaussian Mixture Model...')
		self.gmm.fit(np.reshape(features_PCA, 
								[features_PCA.shape[0]*self.nb_mini_patch, 
								self.keep_PCA]))

		print('Computing Fisher vectors...')
		fisher_train = compute_fisher(features_PCA, self.gmm)

		del(features_PCA)

		# Plotting boxplot

		# for i in range(fisher_train.shape[1]):
		# 	print('Computing dataframe...')
			
		# 	data_real = fisher_train[y_train == 0, i]
		# 	data_cg = fisher_train[y_train == 1, i]

		# 	print('Plotting boxplot...')
		# 	plt.figure()
		# 	plt.boxplot([data_real, data_cg])
		# 	plt.show()

		print('Fitting SVM...')
		self.clf_svm.fit(fisher_train, y_train)
		# clf.fit(np.reshape(features_PCA, [nb_train_batch*batch_size, n_comp*nb_mini_patch]), y_train)

		# print('Fitting MLP...')
		# clf_mlp.fit(fisher_train, y_train)


		del(fisher_train, y_train)

		print('Dumping model...')

		dump_model(self, self.model_directory + '/' + self.run_name + '.pkl')


	def test(self, nb_test_batch, batch_size = 50):

		print('Testing...')
		features_test = np.empty([nb_test_batch*batch_size, 128, self.nb_mini_patch])
		y_test = np.empty([nb_test_batch*batch_size, ])

		data_test = []
		for i in range(nb_test_batch):
			print('Getting batch ' + str(i+1) + '/' + str(nb_test_batch))
			images_batch, y_batch = self.data.get_batch_test(batch_size = batch_size,
													   	crop = False)
			data_test.append([images_batch, y_batch])

		pool = Pool()  

		to_compute = [i for i in range(nb_test_batch)]
		result = pool.starmap(partial(compute_features, 
								  batch_size = batch_size, 
								  nb_mini_patch = self.nb_mini_patch, 
								  nb_batch = nb_test_batch,
								  only_green = self.only_green),
								  zip(data_test, to_compute)) 


		del(data_test)

		index = 0
		for i in range(len(result)):
			features_test[index:index+batch_size] = result[i][0]
			y_test[index:index+batch_size] = result[i][1]

			index+=batch_size

		del(result)

		print('Dimension reduction...')
		features_test_PCA = np.empty([nb_test_batch*batch_size, self.keep_PCA, self.nb_mini_patch])
		for i in range(self.nb_mini_patch):
			# normalize(features_test[:,:,i])
			# features_test_PCA[:,:,i] = pca.transform(features_test[:,:,i])
			features_test_PCA[:,:,i] = self.PCAs[i].transform(features_test[:,:,i])

		del(features_test)

		print('Computing Fisher vectors...')
		fisher_test = compute_fisher(features_test_PCA, self.gmm)

		del(features_test_PCA)



		print('Prediction...')
		y_pred_svm = self.clf_svm.predict(fisher_test)
		# y_pred = clf.predict(np.reshape(features_test_PCA, [nb_test_batch*batch_size, n_comp*nb_mini_patch]))
		
		# y_pred_mlp = clf_mlp.predict(fisher_test)

		print('Computing score...')
		score_svm = accuracy_score(y_pred_svm, y_test)
		# score_mlp = accuracy_score(y_pred_mlp, y_test)

		print('Accuracy SVM : ' + str(score_svm))
		# print('Accuracy MLP : ' + str(score_mlp))




if __name__ == '__main__':

	config = 'server'

	if config == 'server':
		data_directory = '/work/smg/v-nicolas/level-design_raise_100/'
		model_directory = '/work/smg/v-nicolas/models_texture/'
	else:
		data_directory = '/home/nicolas/Database/level-design_raise_100_color/'
		model_directory = '/home/nicolas/Documents/models_texture/'
	image_size = 100

	only_green = True

	nb_train_batch = 50
	nb_test_batch = 10
	batch_size = 50

	model = Texture_model(data_directory, model_directory, 
						  image_size = image_size, keep_PCA = 64, 
						  K_gmm = 32, only_green = only_green)

	model.train(nb_train_batch, batch_size)

	model.test(nb_test_batch, batch_size)

	model2 = load_model(model_directory + 'model1.pkl')

