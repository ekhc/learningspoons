# -*- coding: utf-8 -*-
import tensorflow as tf
import sys
import numpy as np
from configs import DEFINES


def make_lstm_cell(mode, hiddenSize, index):
    cell = tf.nn.rnn_cell.BasicLSTMCell(hiddenSize, name="lstm" + str(index), state_is_tuple=False)
    if mode == tf.estimator.ModeKeys.TRAIN:
        cell = tf.contrib.rnn.DropoutWrapper(cell, output_keep_prob=DEFINES.dropout_width)
    return cell

def model(features, labels, mode, params):
    TRAIN = mode == tf.estimator.ModeKeys.TRAIN
    EVAL = mode == tf.estimator.ModeKeys.EVAL
    PREDICT = mode == tf.estimator.ModeKeys.PREDICT

    initializer = tf.contrib.layers.xavier_initializer()

    embedding_encoder = tf.get_variable(name="embedding_encoder",  
                                        shape=[params['vocabulary_length'], params['embedding_size']],  
                                        dtype=tf.float32,  
                                        initializer=initializer,  
                                        trainable=True)  

    embedding_encoder_batch = tf.nn.embedding_lookup(params=embedding_encoder, ids=features['input'])

    embedding_decoder = tf.get_variable(name="embedding_decoder",  
                                        shape=[params['vocabulary_length'], params['embedding_size']],  
                                        dtype=tf.float32,  
                                        initializer=initializer,  
                                        trainable=True)  

    with tf.variable_scope('encoder_scope', reuse=tf.AUTO_REUSE):
        encoder_cell_list = [make_lstm_cell(mode, params['hidden_size'], i) for i in range(params['layer_size'])]
        rnn_cell = tf.contrib.rnn.MultiRNNCell(encoder_cell_list, state_is_tuple=False)

        encoder_outputs, encoder_states = tf.nn.dynamic_rnn(cell=rnn_cell,  
                                                              inputs=embedding_encoder_batch,  
                                                              dtype=tf.float32)  

    with tf.variable_scope('decoder_scope', reuse=tf.AUTO_REUSE):
        decoder_cell_list = [make_lstm_cell(mode, params['hidden_size'], i) for i in range(params['layer_size'])]
        rnn_cell = tf.contrib.rnn.MultiRNNCell(decoder_cell_list, state_is_tuple=False)

        decoder_state = encoder_states

        predict_tokens = list()
        temp_logits = list()

        attention_plot = tf.get_variable("attention_plot", [DEFINES.max_sequence_length, DEFINES.max_sequence_length], dtype=tf.float32, trainable=False)
        output_token = tf.ones(shape=(tf.shape(encoder_outputs)[0],), dtype=tf.int32) * 1

        for i in range(DEFINES.max_sequence_length):
            if TRAIN:
                if i > 0:
                    input_token_emb = tf.cond(
                        tf.logical_and( 
                            True,
                            tf.random_uniform(shape=(), maxval=1) <= params['teacher_forcing_rate'] 
                        ),
                        lambda: tf.nn.embedding_lookup(embedding_decoder, labels[:, i-1]),  
                        lambda: tf.nn.embedding_lookup(embedding_decoder, output_token) 
                    )
                else:
                    input_token_emb = tf.nn.embedding_lookup(embedding_decoder, output_token)
            else: 
                input_token_emb = tf.nn.embedding_lookup(embedding_decoder, output_token)
                
            #visualization
            #if PREDICT:
                #attention_plot = np.zeros((DEFINES.max_sequence_length, DEFINES.max_sequence_length))
                #attention_plot = tf.zeros((DEFINES.max_sequence_length, DEFINES.max_sequence_length))
                #attention_plot = tf.get_variable("attention_plot", [25, 25], dtype=tf.float32, trainable=False)
                #attention_plot = list()
            
            # 어텐션 적용 부분
            W1 = tf.keras.layers.Dense(params['hidden_size'])
            W2 = tf.keras.layers.Dense(params['hidden_size'])
            V = tf.keras.layers.Dense(1)
            # (?, 256) -> (?, 128)
            hidden_with_time_axis = W2(decoder_state)
            # (?, 128) -> (?, 1, 128)
            hidden_with_time_axis = tf.expand_dims(hidden_with_time_axis, axis=1)
            # (?, 1, 128) -> (?, 25, 128)
            hidden_with_time_axis = tf.manip.tile(hidden_with_time_axis, [1, DEFINES.max_sequence_length, 1])
            # (?, 25, 1)
            score = V(tf.nn.tanh(W1(encoder_outputs) + hidden_with_time_axis))
            # score = V(tf.nn.tanh(W1(encoderOutputs) + tf.manip.tile(tf.expand_dims(W2(decoder_state), axis=1), [1, DEFINES.maxSequenceLength, 1])))
            # (?, 25, 1)
            attention_weights = tf.nn.softmax(score, axis=-1)
            # (?, 25, 128)
            context_vector = attention_weights * encoder_outputs
            # (?, 25, 128) -> (?, 128)
            context_vector = tf.reduce_sum(context_vector, axis=1)
            # (?, 256)
            input_token_emb = tf.concat([context_vector, input_token_emb], axis=-1)
            #visualization
            if PREDICT:
                attention_weights = tf.reshape(attention_weights, (-1, ))
                #attention_plot[i] = attention_weights
                attention_plot[i].assign(attention_weights)
                #print(i)
                #get_attention_weights = tf.contrib.util.make_ndarray(attention_weights)
                #get_attention_weights = tf.Print(attention_weights, [attention_weights], "attention_weights")
                #print(get_attention_weights)
                    #attention_plot[i] = attention_weights.numpy()
                    #attention_plot[i] = attention_weights.eval(session= sess.graph.as_graph_def()) 
                #attention_plot.append(attention_weights)
                
            input_token_emb = tf.keras.layers.Dropout(0.5)(input_token_emb)
            decoder_outputs, decoder_state = rnn_cell(input_token_emb, decoder_state)
            decoder_outputs = tf.keras.layers.Dropout(0.5)(decoder_outputs)
    
            output_logits = tf.layers.dense(decoder_outputs, params['vocabulary_length'], activation=None)

            output_probs = tf.nn.softmax(output_logits)
            output_token = tf.argmax(output_probs, axis=-1)

            predict_tokens.append(output_token)
            temp_logits.append(output_logits)

        predict = tf.transpose(tf.stack(predict_tokens, axis=0), [1, 0])
        logits = tf.transpose(tf.stack(temp_logits, axis=0), [1, 0, 2])

    if PREDICT:
        predictions = {  
            'indexs': predict,  
            'logits': logits 
        }

        return tf.estimator.EstimatorSpec(mode, predictions=predictions)

    labels_ = tf.one_hot(labels, params['vocabulary_length'])

    #loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(logits=logits, labels=labels_))

    loss = tf.reduce_mean(tf.losses.softmax_cross_entropy(logits=logits, onehot_labels=labels_, label_smoothing=0.2))

    accuracy = tf.metrics.accuracy(labels=labels, predictions=predict, name='accOp')

    metrics = {'accuracy': accuracy}
    tf.summary.scalar('accuracy', accuracy[1])

    if EVAL:
        return tf.estimator.EstimatorSpec(mode, loss=loss, eval_metric_ops=metrics)

    assert TRAIN

    optimizer = tf.train.AdamOptimizer(learning_rate=DEFINES.learning_rate)
    train_op = optimizer.minimize(loss, global_step=tf.train.get_global_step())

    return tf.estimator.EstimatorSpec(mode, loss=loss, train_op=train_op)