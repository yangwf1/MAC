import numpy as np
import tensorflow as tf
from tensorflow.python.framework import dtypes
from cnn import fc_layer as fc
import mpu 
from dataset import TestingDataSet
from dataset import TrainingDataSet


class acl_model(object):

    def __init__(self, batch_size, train_csv_path, test_csv_path,test_visual_feature_dir,sliding_dir,sliding_training_sample_file, test_clip_sentence_pairs_path, test_swin_txt_path, train_softmax_dir, test_softmax_dir):

        self.batch_size = batch_size
        self.test_batch_size = 1
        self.vs_lr = 0.005
        self.lambda_regression = 0.01
        self.alpha = 1.0/batch_size
        self.semantic_size = 1024 # the size of visual and semantic comparison size
        self.action_semantic_size = 300
        self.sentence_embedding_size = 4800
        self.visual_feature_dim = 4096*3

        self.train_set=TrainingDataSet(sliding_dir, sliding_training_sample_file, train_csv_path, batch_size, train_softmax_dir)
        self.test_set=TestingDataSet(test_visual_feature_dir, test_csv_path, self.test_batch_size, test_swin_txt_path, test_softmax_dir, test_clip_sentence_pairs_path)


    '''
    used in training alignment+regression model, CTRL(reg)
    '''
    def fill_feed_dict_train_reg(self):
        image_batch, sentence_batch, offset_batch, softmax_batch, VP_spacy_batch, subj_spacy_batch, obj_spacy_batch, simi_mat_img = self.train_set.next_batch_iou()
        input_feed = {
                self.visual_featmap_ph_train: image_batch,
                self.sentence_ph_train: sentence_batch,
                self.offset_ph: offset_batch,
                self.softmax_ph_train: softmax_batch,
                self.VP_spacy_ph_train: VP_spacy_batch
        }

        return input_feed

    
    '''
    cross modal processing module
    '''
    def cross_modal_comb(self, visual_feat, sentence_embed, batch_size, semantic_size_here):
        vv_feature = tf.reshape(tf.tile(visual_feat, [batch_size, 1]),
            [batch_size, batch_size, semantic_size_here])
        ss_feature = tf.reshape(tf.tile(sentence_embed,[1, batch_size]),[batch_size, batch_size, semantic_size_here])
        concat_feature = tf.reshape(tf.concat(axis=2,values=[vv_feature, ss_feature]),[batch_size, batch_size, semantic_size_here*2])
        print concat_feature.get_shape().as_list()
        mul_feature = tf.multiply(vv_feature, ss_feature)
        add_feature = tf.add(vv_feature, ss_feature)

        comb_feature = tf.reshape(tf.concat(axis=2, values=[mul_feature, add_feature, concat_feature]),[1, batch_size, batch_size, semantic_size_here*4])
        return comb_feature


    '''
    visual semantic inference, including visual semantic alignment and clip location regression
    '''
    def visual_semantic_infer(self, visual_feature_train, sentence_embed_train, visual_feature_test, sentence_embed_test, softmax_train, softmax_test, VP_embed_train, VP_embed_test):
        name="CTRL_Model"
        with tf.variable_scope(name):
            print "Building training network...............................\n"
            transformed_clip_train = fc('v2s_lt', visual_feature_train, output_dim=self.semantic_size)
            transformed_clip_train_norm = tf.nn.l2_normalize(transformed_clip_train, axis=1)
            transformed_sentence_train = fc('s2s_lt', sentence_embed_train, output_dim=self.semantic_size)
            transformed_sentence_train_norm = tf.nn.l2_normalize(transformed_sentence_train, axis=1)
            cross_modal_vis_sent_train = self.cross_modal_comb(transformed_clip_train_norm, transformed_sentence_train_norm, self.batch_size, self.semantic_size)

            # the action semantic
            transformed_softmax_train = fc('soft2s_lt', softmax_train, output_dim=self.action_semantic_size)
            transformed_softmax_train_norm = tf.nn.l2_normalize(transformed_softmax_train, axis=1)
            transformed_VP_train = fc('VP2s_lt', VP_embed_train, output_dim=self.action_semantic_size)
            transformed_VP_train_norm = tf.nn.l2_normalize(transformed_VP_train, axis=1)
            cross_modal_action_train = self.cross_modal_comb(transformed_softmax_train_norm, transformed_VP_train_norm, self.batch_size, self.action_semantic_size)

            # may not need normalization
            cross_modal_vis_sent_train = tf.nn.l2_normalize(cross_modal_vis_sent_train, axis=3)
            cross_modal_action_train = tf.nn.l2_normalize(cross_modal_action_train, axis=3)

            # concatenate two
            cross_modal_train = tf.concat([cross_modal_vis_sent_train, cross_modal_action_train], axis=3)

            sim_score_mat_train = mpu.vs_multilayer(cross_modal_train, "vs_multilayer_lt", middle_layer_dim=1000)
            sim_score_mat_train = tf.reshape(sim_score_mat_train,[self.batch_size, self.batch_size, 3])


            tf.get_variable_scope().reuse_variables()
            print "Building test network...............................\n"
            transformed_clip_test = fc('v2s_lt', visual_feature_test, output_dim=self.semantic_size)
            transformed_clip_test_norm = tf.nn.l2_normalize(transformed_clip_test, axis=1)
            transformed_sentence_test = fc('s2s_lt', sentence_embed_test, output_dim=self.semantic_size)
            transformed_sentence_test_norm = tf.nn.l2_normalize(transformed_sentence_test, axis=1)
            cross_modal_vis_sent_test = self.cross_modal_comb(transformed_clip_test_norm, transformed_sentence_test_norm, self.test_batch_size, self.semantic_size)

            # the action semantic
            transformed_softmax_test = fc('soft2s_lt', softmax_test, output_dim=self.action_semantic_size)
            transformed_softmax_test_norm = tf.nn.l2_normalize(transformed_softmax_test, axis=1)
            transformed_VP_test = fc('VP2s_lt', VP_embed_test, output_dim=self.action_semantic_size)
            transformed_VP_test_norm = tf.nn.l2_normalize(transformed_VP_test, axis=1)
            cross_modal_action_test = self.cross_modal_comb(transformed_softmax_test_norm, transformed_VP_test_norm, self.test_batch_size, self.action_semantic_size)

            # may not need normalization
            cross_modal_vis_sent_test = tf.nn.l2_normalize(cross_modal_vis_sent_test, axis=3)
            cross_modal_action_test = tf.nn.l2_normalize(cross_modal_action_test, axis=3)

            # concatenate two
            cross_modal_test = tf.concat([cross_modal_vis_sent_test, cross_modal_action_test], axis=3)

            sim_score_mat_test = mpu.vs_multilayer(cross_modal_test, "vs_multilayer_lt", reuse=True, middle_layer_dim=1000)
            sim_score_mat_test = tf.reshape(sim_score_mat_test, [3])

            return sim_score_mat_train, sim_score_mat_test


    '''
    compute alignment and regression loss
    '''
    def compute_loss_reg(self, sim_reg_mat, offset_label):

        sim_score_mat, p_reg_mat, l_reg_mat = tf.split(axis=2, num_or_size_splits=3, value=sim_reg_mat)
        sim_score_mat = tf.reshape(sim_score_mat, [self.batch_size, self.batch_size])
        l_reg_mat = tf.reshape(l_reg_mat, [self.batch_size, self.batch_size])
        p_reg_mat = tf.reshape(p_reg_mat, [self.batch_size, self.batch_size])
        # unit matrix with -2
        I_2 = tf.diag(tf.constant(-2.0, shape=[self.batch_size]))
        all1 = tf.constant(1.0, shape=[self.batch_size, self.batch_size])
        #               | -1  1   1...   |

        #   mask_mat =  | 1  -1  -1...   |

        #               | 1   1  -1 ...  |
        mask_mat = tf.add(I_2, all1)
        # loss cls, not considering iou
        I = tf.diag(tf.constant(1.0, shape=[self.batch_size]))
        I_half = tf.diag(tf.constant(0.5, shape=[self.batch_size]))
        batch_para_mat = tf.constant(self.alpha, shape=[self.batch_size, self.batch_size])
        para_mat = tf.add(I,batch_para_mat)
        loss_mat = tf.log(tf.add(all1, tf.exp(tf.multiply(mask_mat, sim_score_mat))))
        loss_mat = tf.multiply(loss_mat, para_mat)
        loss_align = tf.reduce_mean(loss_mat)
        # regression loss
        l_reg_diag = tf.matmul(tf.multiply(l_reg_mat, I), tf.constant(1.0, shape=[self.batch_size, 1]))
        p_reg_diag = tf.matmul(tf.multiply(p_reg_mat, I), tf.constant(1.0, shape=[self.batch_size, 1]))
        offset_pred = tf.concat([p_reg_diag, l_reg_diag], 1)
        loss_reg = tf.reduce_mean(tf.abs(tf.subtract(offset_pred, offset_label)))

        loss=tf.add(tf.multiply(self.lambda_regression, loss_reg), loss_align)
        return loss, offset_pred, loss_reg


    def init_placeholder(self):
        visual_featmap_ph_train = tf.placeholder(tf.float32, shape=(self.batch_size, self.visual_feature_dim))
        sentence_ph_train = tf.placeholder(tf.float32, shape=(self.batch_size, self.sentence_embedding_size))
        softmax_ph_train = tf.placeholder(tf.float32, shape=(self.batch_size, self.train_set.clip_softmax_dim))
        offset_ph = tf.placeholder(tf.float32, shape=(self.batch_size,2))
        VP_spacy_ph_train = tf.placeholder(tf.float32, shape=(self.batch_size, self.train_set.spacy_vec_dim*2))

        visual_featmap_ph_test = tf.placeholder(tf.float32, shape=(self.test_batch_size, self.visual_feature_dim))
        sentence_ph_test = tf.placeholder(tf.float32, shape=(self.test_batch_size, self.sentence_embedding_size))
        softmax_ph_test = tf.placeholder(tf.float32, shape=(self.test_batch_size, self.test_set.clip_softmax_dim))
        VP_spacy_ph_test = tf.placeholder(tf.float32, shape=(self.test_batch_size, self.test_set.spacy_vec_dim*2))

        return visual_featmap_ph_train, sentence_ph_train, offset_ph, visual_featmap_ph_test, sentence_ph_test, softmax_ph_train, softmax_ph_test, VP_spacy_ph_train, VP_spacy_ph_test
 

    def get_variables_by_name(self,name_list):
        v_list = tf.trainable_variables()
        v_dict = {}
        for name in name_list:
            v_dict[name] = []
        for v in v_list:
            for name in name_list:
                if name in v.name: v_dict[name].append(v)

        for name in name_list:
            print "Variables of <"+name+">"
            for v in v_dict[name]:
                print "    "+v.name
        return v_dict


    def training(self, loss):
        v_dict = self.get_variables_by_name(["lt"])
        vs_optimizer = tf.train.AdamOptimizer(self.vs_lr, name='vs_adam')
        vs_train_op = vs_optimizer.minimize(loss, var_list=v_dict["lt"])
        return vs_train_op


    def construct_model(self):
        # initialize the placeholder
        self.visual_featmap_ph_train, self.sentence_ph_train, self.offset_ph, self.visual_featmap_ph_test, self.sentence_ph_test, self.softmax_ph_train, self.softmax_ph_test, self.VP_spacy_ph_train, self.VP_spacy_ph_test = self.init_placeholder()

        # build inference network
        sim_reg_mat, sim_reg_mat_test = self.visual_semantic_infer(self.visual_featmap_ph_train, self.sentence_ph_train, self.visual_featmap_ph_test, self.sentence_ph_test, self.softmax_ph_train, self.softmax_ph_test, self.VP_spacy_ph_train, self.VP_spacy_ph_test)
        
        # compute loss
        self.loss_align_reg, offset_pred, loss_reg = self.compute_loss_reg(sim_reg_mat, self.offset_ph)
        # optimize
        self.vs_train_op = self.training(self.loss_align_reg)
        return self.loss_align_reg, self.vs_train_op, sim_reg_mat_test, offset_pred, loss_reg


