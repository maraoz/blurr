# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/02_modeling-core.ipynb (unless otherwise specified).

__all__ = ['hf_splitter', 'HF_BaseModelWrapper', 'HF_BaseModelCallback', 'blurr_module_summary']

# Cell
import torch, nlp
from transformers import *

from fastai.text.all import *
from fastai.callback.hook import _print_shapes

from ..utils import *
from ..data.core import *

logging.set_verbosity_error()

# Cell
def hf_splitter(m):
    """Splits the huggingface model based on various model architecture conventions"""
    model = m.hf_model if (hasattr(m, 'hf_model')) else m
    root_modules = list(model.named_children())
    top_module_name, top_module = root_modules[0]

    groups = L([ m for m_name, m in list(top_module.named_children()) ])
    groups += L([ m for m_name, m in root_modules[1:] ])

    return groups.map(params).filter(lambda el: len(el) > 0)

# Cell
class HF_BaseModelWrapper(Module):
    def __init__(self, hf_model, output_hidden_states=False, output_attentions=False, hf_model_kwargs={}):
        super().__init__()

        store_attr(self=self, names='output_hidden_states, output_attentions, hf_model_kwargs')
        self.hf_model = hf_model.cuda() if torch.cuda.is_available() else hf_model

        n_fwd_args = self.hf_model.forward.__code__.co_argcount
        self.hf_model_fwd_args = self.hf_model.forward.__code__.co_varnames[:n_fwd_args][1:]

    def forward(self, x):
        for k in list(x):
            if k not in self.hf_model_fwd_args: del x[k]

        return self.hf_model(**x,
                             output_hidden_states=self.output_hidden_states,
                             output_attentions=self.output_hidden_states,
                             return_dict=True,
                             **self.hf_model_kwargs)

# Cell
class HF_BaseModelCallback(Callback):

    def before_batch(self): self.hf_loss = None

    def after_pred(self):
        model_outputs = self.pred
        self.learn.blurr_model_outputs = {}

        for k,v in model_outputs.items():
            # if the "labels" are included, we are training with target labels in which case the loss is returned
            if (k == 'loss'):
                self.hf_loss = v
            # the logits represent the prediction
            elif (k == 'logits'):
                self.learn.pred = v
            # add any other things included in model_outputs as blurr_{model_output_key}
            else:
                self.learn.blurr_model_outputs[k] = v

    def after_loss(self):
        # if we already have the loss from the model, update the Learner's loss to be it
        if (self.hf_loss is not None): self.learn.loss = self.hf_loss

# Cell
def blurr_module_summary(learn, *xb):
    "Print a summary of `model` using `xb`"
    infos = layer_info(learn, *xb)
    n,bs = 64,find_bs(xb)
    inp_sz = _print_shapes(apply(lambda x:x.shape,  xb[0]['input_ids']), bs)
    res = f"{learn.model.__class__.__name__} (Input shape: {inp_sz})\n"
    res += "=" * n + "\n"
    res += f"{'Layer (type)':<20} {'Output Shape':<20} {'Param #':<10} {'Trainable':<10}\n"
    res += "=" * n + "\n"
    ps,trn_ps = 0,0
    infos = [o for o in infos if o is not None] #see comment in previous cell
    for typ,np,trn,sz in infos:
        if sz is None: continue
        ps += np
        if trn: trn_ps += np
        res += f"{typ:<20} {_print_shapes(sz, bs)[:19]:<20} {np:<10,} {str(trn):<10}\n"
        res += "_" * n + "\n"
    res += f"\nTotal params: {ps:,}\n"
    res += f"Total trainable params: {trn_ps:,}\n"
    res += f"Total non-trainable params: {ps - trn_ps:,}\n\n"
    return PrettyString(res)

# Cell
@patch
def blurr_summary(self:Learner):
    "Print a summary of the model, optimizer and loss function."
    xb = self.dls.train.one_batch()[:self.dls.train.n_inp]
    res = blurr_module_summary(self, *xb)
    res += f"Optimizer used: {self.opt_func}\nLoss function: {self.loss_func}\n\n"
    if self.opt is not None:
        res += f"Model " + ("unfrozen\n\n" if self.opt.frozen_idx==0 else f"frozen up to parameter group #{self.opt.frozen_idx}\n\n")
    res += "Callbacks:\n" + '\n'.join(f"  - {cb}" for cb in sort_by_run(self.cbs))
    return PrettyString(res)

# Cell
@typedispatch
def show_results(x:HF_BaseInput, y, samples, outs, learner, ctxs=None, max_n=6, **kwargs):
    kwargs['hf_tokenizer'] = learner.dls.before_batch[0].hf_tokenizer

    if ctxs is None: ctxs = get_empty_df(min(len(samples), max_n))
    ctxs = show_batch[object](x, y, samples, max_n=max_n, ctxs=ctxs, **kwargs)

    n_preds_per_input = len(outs[0])
    if (n_preds_per_input == 1):
        for i,ctx in enumerate(ctxs): ctx['target'] = outs[i][0]
    else:
        for pred_idx in range(n_preds_per_input):
            for i,ctx in enumerate(ctxs):  ctx[f'target{pred_idx+1}'] = outs[i][pred_idx]

    display_df(pd.DataFrame(ctxs))
    return ctxs

# Cell
@patch
def blurr_predict(self:Learner, item, rm_type_tfms=None, with_input=False):
    dl = self.dls.test_dl([item], rm_type_tfms=rm_type_tfms, num_workers=0)

    # this is where we have to change things up since a blurr "input" is represented by a dictionary of
    # tensors (input_ids, attention_mask, token_type_ids, etc...) and not a single tensor (which fastai assumes
    # in a number of places)
    b = dl.one_batch()
    inp = b[0]
    preds, _, dec_preds = self.get_preds(dl=dl, with_input=False, with_decoded=True)

    i = getattr(self.dls, 'n_inp', -1)
    inp = (inp,) if i==1 else tuplify(inp)
    dec = self.dls.decode_batch(inp + tuplify(dec_preds))[0]
    dec_inp,dec_targ = map(detuplify, [dec[:i],dec[i:]])
    res = dec_targ,dec_preds[0],preds[0]
    if with_input: res = (dec_inp,) + res
    return res