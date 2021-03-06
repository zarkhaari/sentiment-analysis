import numpy as np
import pandas as pd
import pickle
import sys
from tqdm import tqdm
import nltk

from keras.models import Model, Sequential
from keras.layers import Input, Dense, Flatten, Conv1D, MaxPooling1D, Dropout, LSTM
from keras.callbacks import EarlyStopping, ModelCheckpoint
from keras import activations, initializers, regularizers, constraints
from keras.preprocessing.sequence import pad_sequences
from keras.preprocessing.text import Tokenizer
from keras.layers.embeddings import Embedding
from keras.utils import np_utils
from sklearn.model_selection import train_test_split
from keras.models import load_model

from text_preprocessor import TextPreprocessor

from sklearn.metrics import confusion_matrix, classification_report
from keras import optimizers

VECTORIZER_FILE = 'vect_lstm_pretrained_lr2.pkl'
MODEL_FILE = 'sentiment_lstm_pretrained_lr2.hdf5'
CHECKPOINT_FILE = 'sentiment_lstm_weights_pretrained_lr2.hdf5'
GLOVE = 'glove.twitter.27B.100d.txt'

EPOCHS = 10
BATCH_SIZE= 128
EMBED_DIMS = 100

MAX_LEN = 60

class SentimentAnalysisLstm:
  def __init__(self, train_filename='data/full_preprocessed_sergio.csv', test_filename='data/minnesota_test.csv', is_brand=True):
    columns=['id', 'Query Name', 'text', 'label', 'clean_text']
    self.df = pd.read_csv(train_filename, header=None, names=columns, encoding = "ISO-8859-1")

    self.df = self.df[pd.notnull(self.df['clean_text'])]

    self.df['max_len'] = self.df['clean_text'].apply(lambda x: len(x))
    self.max_len = 290 # self.df['max_len'].max() + 1 ## requires more memory
    print('max sentence length', self.df['max_len'].max())

    self.dftest = self.read_brand_test_data(test_filename, is_brand)
    self.vect = None

  def train(self):
    filepath="saved_models/{}".format(CHECKPOINT_FILE)

    X = self.word_embeddings(self.df['clean_text'].values, self.max_len)
    y = np_utils.to_categorical(self.df['label'].values)

    X_train, X_val, Y_train, Y_val = train_test_split(X,y, test_size = 0.3, random_state = 42)

    self.embed_dict = self.create_word_embeddings_dict()
    self.embed_matrix = self.create_word_embeddings_matrix(self.embed_dict)

    model = self.build_model(self.max_len)

    checkpoint = ModelCheckpoint(filepath, monitor='val_acc', verbose=1, save_best_only=True, mode='max')

    history = model.fit(X_train, Y_train, batch_size=BATCH_SIZE, epochs=EPOCHS, validation_data=(X_val, Y_val), callbacks = [checkpoint])

    model.save("saved_models/{}".format(MODEL_FILE))

    score,acc = model.evaluate(X_val, Y_val, verbose = 2, batch_size = BATCH_SIZE)
    print("score: %.2f" % (score))
    print("acc: %.2f" % (acc))

  def build_model(self, max_len):
    model = Sequential()
    model.add(Embedding(self.vocab_size, EMBED_DIMS, input_length=max_len, weights=[self.embed_matrix], trainable=False))

    #model.add(Dropout(0.5))
    model.add(LSTM(100, dropout=0.2, recurrent_dropout=0.2))
    model.add(Dense(3,activation='softmax'))

    # adam default parameters:  lr=0.001, beta_1=0.9, beta_2=0.999, epsilon=1e-08, decay=0.0.
    adam = optimizers.Adam(lr=0.001, beta_1=0.9, beta_2=0.999, epsilon=None, decay=0.0, amsgrad=False)
    model.compile(loss='categorical_crossentropy', optimizer=adam, metrics=['accuracy'])
    model.summary()
    return model

  def create_word_embeddings_matrix(self, embed_dict):
    emb_matrix = np.zeros((self.vocab_size, EMBED_DIMS))
    for w, i in self.tokenizer.word_index.items():
        if i < self.vocab_size:
            vect = embed_dict.get(w)
            if vect is not None:
              emb_matrix[i] = vect
        else:
            break
    return emb_matrix

  def create_word_embeddings_dict(self):
    filename = "data/{}".format(GLOVE)
    emb_dict = {}
    glove = open(filename, 'r', encoding = "utf-8")
    for line in glove:
        values = line.split()
        word = values[0]
        vector = np.asarray(values[1:], dtype='float32')
        emb_dict[word] = vector
    glove.close()
    return emb_dict

  def word_embeddings(self, texts, max_len):
    # self.tokenizer = Tokenizer(num_words=max_fatures)
    self.tokenizer = Tokenizer()
    self.tokenizer.fit_on_texts(texts)

    sequences = self.tokenizer.texts_to_sequences(texts)
    self.vocab_size = len(self.tokenizer.word_index) + 1
    print('Found %d unique words.' % len(self.tokenizer.word_index))

    x_train = pad_sequences(sequences, maxlen=max_len)

    with open("saved_models/{}".format(VECTORIZER_FILE), 'wb') as handle:
      pickle.dump(self.tokenizer, handle, protocol = pickle.HIGHEST_PROTOCOL)
      print ('tokenizer saved')

    return x_train

  def read_brand_test_data(self, test_filename, is_brand=True):

    if is_brand:
      df = pd.read_csv(test_filename)
      df2 = pd.read_csv('data/minnesota_test2.csv')
      df = df.append(df2, ignore_index=True, sort=True)
      df = df[~df['Sentiment'].apply(self.is_not_ascii)]
      df = df.rename(columns={'Snippet': 'text', 'Sentiment': 'label'})

      #df = df[df.label != 'neutral']
      #df['label'] = df['label'].apply(lambda x: 0 if x == 'negative' else 4)
      di = { 'positive': 2, 'neutral': 1, 'negative': 0 }
      df["label"].replace(di, inplace=True)
    else:
      columns=['label', 'id', 'created_at', 'query', 'user', 'text']
      df = pd.read_csv(test_filename, header=None, names=columns)
      df = df[(df.label == 4) | (df.label == 0)]

    return df

  def load_pretrained_model(self):
    self.model = load_model("saved_models/{}".format(MODEL_FILE))
    with open("saved_models/{}".format(VECTORIZER_FILE), 'rb') as f2:
      self.vect = pickle.load(f2)
    return self.model

  def predict(self, model):
    tqdm.pandas()
    print('preprocessing test data...')
    tp = TextPreprocessor()
    self.dftest['clean_text'] = self.dftest['text'].progress_apply(tp.pre_process_text_no_stemming)

    print('word embeddings test data...')
    sequences = self.vect.texts_to_sequences(self.dftest['clean_text'].values)

    X_test = pad_sequences(sequences, maxlen=self.max_len)
    y_test = self.dftest['label'].values
    print('predict...')

    preds = model.predict(X_test)
    y_preds = [self.prob_to_sentiment_label(pred) for pred in preds]

    prob_map = ['negative', 'neutral', 'positive']

    probs = []
    for pred in preds:
      di = {}
      for i, prob in enumerate(pred):
        di[prob_map[i]] = prob
      probs.append(di)

    ##probs = ["{}:{}".format(prob_map[i[0]], prob) for i, prob in enumerate(preds)]

    self.dftest['pred'] = y_preds
    self.dftest['prob'] = probs

    submission = self.dftest[['text', 'label', 'pred', 'prob']]

    submission.to_csv('data/predictions_3_categories.csv')

    # print(classification_report(y_test, y_preds))

    score,acc = model.evaluate(X_test, np_utils.to_categorical(self.dftest['label'].values), verbose = 2, batch_size = 128)
    print("score: %.2f" % (score))
    print("acc: %.2f" % (acc))

    return y_preds

  def predict_single_text(self, model, text):
    sequences = self.vect.texts_to_sequences([text])
    X_test = pad_sequences(sequences, maxlen=self.max_len)
    print('predict...')
    pred = model.predict(X_test)[0]
    prob_map = ['NEGATIVE', 'NEUTRAL', 'POSITIVE']
    print('****************')
    print(prob_map[np.argmax(pred)])
    print('****************')

  def prob_to_sentiment_label(self, pred):
    #THRESHOLD = .4
    #return 0 if pred[0] > THRESHOLD else 1

    return np.argmax(pred)

  def decode_sentiment(self, pred):
    return 'POSITIVE' if self.prob_to_sentiment_label(pred) == 1 else 'NEGATIVE'

  def is_not_ascii(self, string):
    return string is not None and any([ord(s) >= 128 for s in string])

  def preds(self):
    df = pd.read_csv('data/predictions_3_categories.csv')

    correct = 0
    incorrect = 0

    for i, row in df.iterrows():
      if (row['label'] == row['pred']):
        correct += 1
      else:
        incorrect += 1
    print('correct', correct)
    print('incorrect', incorrect)

    print(correct / df.shape[0])


nltk.download('punkt')
nltk.download('stopwords')

'''
  --------------------------------------------------
  MAIN
  --------------------------------------------------
'''

if len(sys.argv) == 1:
  print("task name is required. USAGE: python3 <filename> <task>")
elif sys.argv[1] == 'train':
  analyzer = SentimentAnalysisLstm()
  analyzer.train()
elif sys.argv[1] == 'test':
  analyzer = SentimentAnalysisLstm(train_filename='data/full_no_stem_preprocessed.csv', test_filename='data/minnesota_test.csv', is_brand=True)
  model = analyzer.load_pretrained_model()
  preds = analyzer.predict(model)
elif sys.argv[1] == 'debug':
  analyzer = SentimentAnalysisLstm()
  model = analyzer.load_pretrained_model()
  analyzer.predict_single_text(model, "The sun is shining, everything is beautiful and I'm happy")
elif sys.argv[1] == 'preds':
  analyzer = SentimentAnalysisLstm()
  analyzer.preds()