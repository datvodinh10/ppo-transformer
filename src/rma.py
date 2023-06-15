import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

class RelativeMultiheadAttention(nn.Module):
    """Calculate Relative Multihead Attention"""
    def __init__(self,
                 embed_dim:int,
                 num_heads:int) -> None:

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

        self.U = nn.Parameter(torch.Tensor(self.num_heads,self.heads_dim))
        self.V = nn.Parameter(torch.Tensor(self.num_heads,self.heads_dim))
        nn.init.xavier_uniform_(self.U)
        nn.init.xavier_uniform_(self.V)

        self.out_projection = nn.Linear(embed_dim,embed_dim)

    def forward(self,
                query: torch.Tensor,
                key: torch.Tensor,
                value: torch.Tensor,
                pos_embedding: torch.Tensor,
                mask: None)->torch.Tensor:
        
        # key shape: (batch_size,key_len,embed_size)
        # query shape: (batch_size,query_len,embed_size)
        # value shape: (batch_size,value_len,embed_size)
        
        batch_size = query.shape[0]

        query_len,key_len,value_len = query.shape[1], key.shape[1], value.shape[1]
        
        queries = self.Queries(query).view(batch_size,query_len,self.num_heads,self.heads_dim)
        keys    = self.Keys(key).view(batch_size,key_len,self.num_heads,self.heads_dim)
        values  = self.Values(value).view(batch_size,value_len,self.num_heads,self.heads_dim)
        # keys shape: (batch_size,key_len,num_heads,head_dim)
        # queries shape: (batch_size,query_len,num_heads,head_dim)
        # values shape: (batch_size,value_len,num_heads,head_dim)
        R = self.Pos(pos_embedding).view(batch_size,-1,self.num_heads,self.heads_dim)
        # Relative counterpart R shape: (batch_size,key_len,num_heads,head_dim)

        content_score  = torch.einsum("bqhd,bkhd->bhqk",[queries+self.U,keys])
        position_score = torch.einsum("bqhd,bkhd->bhqk",[queries+self.V,R])
        position_score = self._rel_shift(position_score)

        attention_score = (content_score + position_score) / self.d

        if mask is not None:
            attention_score = attention_score.masked_fill(mask==0,float("-inf"))

        alpha = torch.einsum("bhqk,bvhd->bqhd",[attention_score,values]).view(batch_size,-1,self.embed_dim)
        # alpha shape: (batch_size,query_len,embed_dim)

        return self.out_projection(alpha)
    

    def _rel_shift(self, x: torch.Tensor, zero_upper: bool = False):

        x_padded = F.pad(x, [1, 0])  # step 1
        x_padded = x_padded.view(x.size(0), x.size(1), x.size(3) + 1, x.size(2))  # step 2
        x = x_padded[:, :, 1:].view_as(x)  # step 3
        if zero_upper:
            ones = torch.ones((x.size(2), x.size(3))).unsqueeze(0).unsqueeze(0)
            x = x * torch.tril(ones.to(x.device), x.size(3) - x.size(2))  # step 4
        return x




