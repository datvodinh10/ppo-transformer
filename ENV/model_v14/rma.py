import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

class RelativeMultiheadAttention(nn.Module):
    """Calculate Relative Multihead Attention"""
    def __init__(self,
                 embed_dim:int,
                 num_heads:int) -> None:
        """Overview:
            Init AttentionXL.
        Arguments:
            - embed_dim (:obj:`int`): dimension of embedding
            - num_heads (:obj:`int`): number of heads for multihead attention
        """

        super(RelativeMultiheadAttention,self).__init__()
        self.embed_dim  = embed_dim
        self.d          = np.sqrt(embed_dim)
        self.num_heads  = num_heads
        self.heads_dim  = embed_dim // num_heads
        assert embed_dim % num_heads == 0, "embed_dim % num_heads should be zero."
        
        self.Queries    = nn.Linear(embed_dim,embed_dim)
        self.Keys       = nn.Linear(embed_dim,embed_dim)
        self.Values     = nn.Linear(embed_dim,embed_dim)
        self.Pos        = nn.Linear(embed_dim,embed_dim,bias=False)

        self.out_projection = nn.Linear(embed_dim,embed_dim)

    def forward(self,
                query: torch.Tensor,
                key: torch.Tensor,
                value: torch.Tensor,
                pos_embedding: torch.Tensor,
                U: torch.Tensor,
                V: torch.Tensor,
                mask: None)->torch.Tensor:
        """Overview:
            Compute Relative Multi-head Attention.

        Arguments:
            - query (`torch.Tensor`): attention input of shape (cur_seq, bs, input_dim)
            - key (`torch.Tensor`): attention input of shape (full_seq, bs, input_dim)
            - value (`torch.Tensor`): attention input of shape (full_seq, bs, input_dim)
            - pos_embedding (`torch.Tensor`): positional embedding of shape (full_seq, 1, full_seq)
            - U (`torch.Tensor`): global content bias, shape (num_heads,heads_dim)
            - V (`torch.Tensor`): global position bias, shape (num_heads,heads_dim)
            - mask (`Optional[torch.Tensor|None]`): attention mask of shape (cur_seq, full_seq, 1)
            - padding_mask (`Optional[torch.Tensor|None]`): attention mask of shape (bs,cur_seq, full_seq)
            - full_seq = prev_seq + cur_seq

        Returns:
            - alpha (`torch.Tensor`): attention output of shape (cur_seq, bs, input_dim)
        """

        batch_size = query.shape[1]
        query_len,key_len,value_len = query.shape[0], key.shape[0], value.shape[0]
        
        queries = self.Queries(query).view(query_len,batch_size,self.num_heads,self.heads_dim)
        keys    = self.Keys(key).view(key_len,batch_size,self.num_heads,self.heads_dim)
        values  = self.Values(value).view(value_len,batch_size,self.num_heads,self.heads_dim)
        R       = self.Pos(pos_embedding).view(-1,self.num_heads,self.heads_dim)

        content_score   = torch.einsum("qbhd,kbhd->qkbh",[queries+U,keys])
        position_score  = torch.einsum("qbhd,khd->qkbh",[queries+V,R])
        position_score  = self._rel_shift(position_score)
        attention_score = (content_score + position_score) / self.d # (query_len,key_len,batch_size,num_heads)

        assert torch.isnan(queries+U).any()==False,f"{queries+U}{queries}{U}"
        assert torch.isnan(keys).any()==False,f"{keys}"
        assert torch.isnan(content_score).any()==False, "content score return NaN!" 
        assert torch.isnan(position_score).any()==False, "position score return NaN!" 
        assert torch.isnan(attention_score).any()==False, "attention score return NaN!" 

        if mask is not None:
            mask = mask.unsqueeze(-1)  #  cur_seq x full_seq x 1 x 1
            assert mask.shape[:2] == attention_score.shape[:2] , f"Mask shape: {mask.shape} vs Attention shape: {attention_score.shape}" # check shape of mask
            attention_score = attention_score.masked_fill(mask,float("-1e20")).type_as(attention_score)
                 
        attention_score = torch.softmax(attention_score,dim=1)

        assert torch.isnan(attention_score).any()==False, "attention score return NaN after softmax!" 

        alpha = torch.einsum("qkbh,vbhd->qbhd",[attention_score,values])
        alpha = alpha.contiguous().view(alpha.size(0),alpha.size(1),self.embed_dim) # alpha shape: (query_len,batch_size,embed_dim)

        assert torch.isnan(alpha).any()==False, "RMA alpha return NaN!" 

        return self.out_projection(alpha)
    

    def _rel_shift(self, x: torch.Tensor, zero_triu=False):
        """
        Overview:
            Relatively shift the attention score matrix.

        Example:
            a00 a01 a02      0 a00 a01 a02       0  a00 a01      a02  0  a10     a02  0   0
            a10 a11 a12  =>  0 a10 a11 a12  =>  a02  0  a10  =>  a11 a12  0  =>  a11 a12  0
            a20 a21 a22      0 a20 a21 a22      a11 a12  0       a20 a21 a22     a20 a21 a22

        Arguments:
            - x (`torch.Tensor`): input tensor of shape (cur_seq, full_seq, bs, head_num).
            - zero_upper (`bool`): if True set the upper-right triangle to zero.
            
        Returns:
            - x (`torch.Tensor`): input after relative shift. Shape (cur_seq, full_seq, bs, head_num).
        """
        zero_pad = torch.zeros((x.size(0), 1, *x.size()[2:]), dtype=x.dtype)
        x_padded = torch.cat([zero_pad, x], dim=1)

        x_padded = x_padded.view(x.size(1) + 1, x.size(0), *x.size()[2:])

        x = x_padded[1:].view_as(x)

        if zero_triu:
            ones = torch.ones((x.size(0), x.size(1)))
            x = x * torch.tril(ones, x.size(1) - x.size(0))[:,:,None,None]

        return x




