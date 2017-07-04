import numpy as np
from torch import nn
from torch.nn import init
from torch.nn.functional import elu

from braindecode.torch_ext.init import glorot_weight_zero_bias
from braindecode.torch_ext.modules import Expression
from braindecode.torch_ext.util import np_to_var


class EEGNet(object):
    """
    See https://arxiv.org/pdf/1611.08024.pdf.
    """
    def __init__(self, in_chans,
                 n_classes,
                 final_conv_length='auto',
                 input_time_length=None,
                 pool_mode='max',
                 second_kernel_size=(2,32),
                 third_kernel_size=(8,4),
                 drop_prob=0.25
                 ):

        if final_conv_length == 'auto':
            assert input_time_length is not None
        self.__dict__.update(locals())
        del self.self

    def create_network(self):
        pool_class = dict(max=nn.MaxPool2d, mean=nn.AvgPool2d)[self.pool_mode]
        model = nn.Sequential()
        n_filters_1 = 16
        model.add_module('conv_1', nn.Conv2d(
            self.in_chans, n_filters_1, (1, 1), stride=1, bias=False))
        model.add_module('bnorm_1', nn.BatchNorm2d(
            n_filters_1, momentum=0.1, affine=True),)
        model.add_module('elu_1', Expression(elu))
        # transpose to examples x 1 x (virtual, not EEG) channels x time
        model.add_module('permute_1', Expression(lambda x: x.permute(0,3,1,2)))

        model.add_module('drop_1', nn.Dropout(p=self.drop_prob))

        n_filters_2 = 4
        # not clear to me how they did the padding
        model.add_module('conv_2', nn.Conv2d(
            1, n_filters_2, self.second_kernel_size, stride=1,
            padding=(self.second_kernel_size[0] // 2, 0),
            bias=False))
        model.add_module('bnorm_2',nn.BatchNorm2d(
            n_filters_2, momentum=0.1, affine=True),)
        model.add_module('elu_2', Expression(elu))
        model.add_module('pool_2', pool_class(
            kernel_size=(2, 4), stride=(2, 4)))
        model.add_module('drop_2', nn.Dropout(p=self.drop_prob))

        n_filters_3 = 4
        model.add_module('conv_3', nn.Conv2d(
            n_filters_2, n_filters_3, self.third_kernel_size, stride=1,
            padding=(self.third_kernel_size[0] // 2, 0),
            bias=False))
        model.add_module('bnorm_3',nn.BatchNorm2d(
            n_filters_3, momentum=0.1, affine=True),)
        model.add_module('elu_3', Expression(elu))
        model.add_module('pool_3', pool_class(
            kernel_size=(2, 4), stride=(2, 4)))
        model.add_module('drop_3', nn.Dropout(p=self.drop_prob))



        out = model(np_to_var(np.ones(
            (1, self.in_chans, self.input_time_length, 1),
            dtype=np.float32)))
        n_out_virtual_chans = out.cpu().data.numpy().shape[2]

        if self.final_conv_length == 'auto':
            n_out_time = out.cpu().data.numpy().shape[3]
            self.final_conv_length = n_out_time

        model.add_module('conv_classifier', nn.Conv2d(
            n_filters_3, self.n_classes,
            (n_out_virtual_chans, self.final_conv_length,), bias=True))
        model.add_module('softmax', nn.LogSoftmax())
        # Transpose back to the the logic of braindecode,
        # so time in third dimension (axis=2)
        model.add_module('permute_2', Expression(lambda x: x.permute(0,1,3,2)))
        # remove empty dim at end and potentially remove empty time dim
        # do not just use squeeze as we never want to remove first dim
        def squeeze_output(x):
            assert x.size()[3] == 1
            x = x[:,:,:,0]
            if x.size()[2] == 1:
                x = x[:,:,0]
            return x
        model.add_module('squeeze',  Expression(squeeze_output))
        glorot_weight_zero_bias(model)
        return model