import argparse
import json
import logging
import os
import sys

import torch
import numpy as np
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    EvalPrediction,
    AutoConfig,
    TrainerCallback
    )

from datasets import Dataset
from sklearn.metrics import f1_score, roc_auc_score, accuracy_score, confusion_matrix, precision_score, recall_score
from train.LSTM_attention import *
from train.SpanEMO import *
from train.ASL_loss import *
from train.custom_trainer import *


parser = argparse.ArgumentParser(prog="train", description="Train Table to Text with BART")

g = parser.add_argument_group("Common Parameter")
g.add_argument("--output-dir", type=str, default="/YBEOBE/models/", help="output directory path to save artifacts")
g.add_argument("--model-path", type=str, default="beomi/KcELECTRA-base-v2022", help="model file path")
g.add_argument("--tokenizer", type=str, default="beomi/KcELECTRA-base-v2022", help="huggingface tokenizer path")
g.add_argument("--max-seq-len", type=int, default=218, help="max sequence length")
g.add_argument("--batch-size", type=int, default=32, help="training batch size")
g.add_argument("--valid-batch-size", type=int, default=64, help="validation batch size")
g.add_argument("--accumulate-grad-batches", type=int, default=8, help=" the number of gradident accumulation steps")
g.add_argument("--epochs", type=int, default=30, help="the numnber of training epochs")
g.add_argument("--learning-rate", type=float, default=4e-5, help="max learning rate")
g.add_argument("--weight-decay", type=float, default=0.01, help="weight decay")
g.add_argument("--seed", type=int, default=42, help="random seed")
g.add_argument("--model-choice", type=str, default="AutoModelForSequenceClassification", help="or model or loss function", 
                                            choices=['AutoModelForSequenceClassification', 'LSTM_attention', 'SpanEMO', "ASL_loss"])


def main(args):
    logger = logging.getLogger("train")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
        logger.addHandler(handler)

    os.makedirs(args.output_dir, exist_ok=True)
    logger.info(f'[+] Save output to "{args.output_dir}"')

    logger.info(" ====== Arguements ======")
    for k, v in vars(args).items():
        logger.info(f"{k:25}: {v}")

    logger.info(f"[+] Set Random Seed to {args.seed}")
    np.random.seed(args.seed)
    os.environ["PYTHONHASHSEED"] = str(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed(args.seed)  # type: ignore

    logger.info(f'[+] Load Tokenizer"')
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)

    logger.info(f'[+] Load Dataset')
    train_ds = Dataset.from_json("/YBEOBE/data/nikluge-ea-2023-train.jsonl")
    valid_ds = Dataset.from_json("/YBEOBE/data/nikluge-ea-2023-dev.jsonl")
    test_ds = Dataset.from_json("/YBEOBE/data/nikluge-ea-2023-test.jsonl")

    if args.model_choice == "SpanEMO":
        if args.model_path == "Twitter/twhin-bert-large":
            labels = ['▁행복한', '▁기대', '▁신뢰', '▁놀라운', '▁싫어', '겁', '▁화', '▁눈물']
        else:
            labels = ['기쁜', '기대', '믿는', '놀라운', '싫은', '두려운', '화', '슬픈']
    else:
        labels = list(train_ds["output"][0].keys())
    id2label = {idx:label for idx, label in enumerate(labels)}
    label2id = {label:idx for idx, label in enumerate(labels)}
    with open(os.path.join(args.output_dir, "label2id.json"), "w") as f:
        json.dump(label2id, f)

    def preprocess_data(examples):
        if args.model_choice == "SpanEMO":
            if args.model_path == "Twitter/twhin-bert-large":
                text1 = '행복한 기대하는 신뢰하는 놀라운 싫어하는 겁나는 화나는 눈물나는 감정이 든다'
                text2 = examples["input"]["form"]

                key_mapping = {
                    "joy": "▁행복한",
                    "anticipation": "▁기대",
                    "trust": "▁신뢰",
                    "surprise": "▁놀라운",
                    "disgust": "▁싫어",
                    "fear": "겁",
                    "anger": "▁화",
                    "sadness": "▁눈물"
                }
            else:
                text1 = '기쁜 기대하는 믿는 놀라운 싫은 두려운 화난 슬픈 감정이 든다'
                text2 = examples["input"]["form"]               

                key_mapping = {
                    "joy": "기쁜",
                    "anticipation": "기대",
                    "trust": "믿는",
                    "surprise": "놀라운",
                    "disgust": "싫은",
                    "fear": "두려운",
                    "anger": "화",
                    "sadness": "슬픈"
                }

            # encode them
            encoding = tokenizer(text1, text2, padding="max_length", truncation=True, max_length=args.max_seq_len)
        

            # add labels
            if examples["output"] != "":
                encoding["labels"] = [0.0] * len(labels)
                for key in key_mapping:
                    if examples["output"][key] == 'True':
                        encoding["labels"][label2id[key_mapping[key]]] = 1.0

            # 감정레이블의 인덱스 구하기
            input_ids = encoding['input_ids']
            encoding['label_idxs'] = [tokenizer.convert_ids_to_tokens(input_ids).index(labels[idx])
                                      for idx, _ in enumerate(labels)]

        else:
          # take a batch of texts
          text1 = examples["input"]["form"]
          text2 = examples["input"]["target"]["form"]
          target_begin = examples["input"]["target"].get("begin")
          target_end = examples["input"]["target"].get("end")

          # encode them
          encoding = tokenizer(text1, text2, padding="max_length", truncation=True, max_length=args.max_seq_len)
          # add labels
          if examples["output"] != "":
              encoding["labels"] = [0.0] * len(labels)
              for key, idx in label2id.items():
                  if examples["output"][key] == 'True':
                    encoding["labels"][idx] = 1.0

          # 타겟 찾기 (attention 위해)
          encoding["target_positions"] = [0] * len(encoding['input_ids'])  # 문장 길이만큼 0으로 초기화

          if text2 != None:
              encoded_target = tokenizer(text2, add_special_tokens=False)["input_ids"]
              encoded_text = tokenizer(text1, add_special_tokens=False)["input_ids"]

              for i in range(len(encoded_text) - len(encoded_target) + 1):
                  if encoded_text[i:i+len(encoded_target)] == encoded_target:
                      target_begin = i + 1  # [CLS] 떄문에 + 1
                      target_end = i + len(encoded_target) + 1  # 나중에 리스트 슬라이싱 때문에 + 1
                      break

          # Mark the target positions with 1
              for i in range(target_begin, target_end):
                  encoding["target_positions"][i] = 1  # 타겟이면 1, 타겟이 아니면 0

        return encoding


    encoded_tds = train_ds.map(preprocess_data, remove_columns=train_ds.column_names)
    encoded_vds = valid_ds.map(preprocess_data, remove_columns=valid_ds.column_names)
    encoded_test_ds = test_ds.map(preprocess_data, remove_columns=train_ds.column_names)

    logger.info(f'[+] Load Model from "{args.model_path}"')
        
    model_choices = {
                    "LSTM_attention": LSTMAttention,
                    "SpanEMO": SpanEmo
                    }

    common_params = {
        'model_path': args.model_path,
        'problem_type': "multi_label_classification",
        'num_labels': len(labels),
        'id2label': id2label,
        'label2id': label2id
    }

    ModelClass = model_choices.get(args.model_choice)


    if args.model_choice in model_choices:
        common_params['output_hidden_states'] = True
        model = ModelClass(**common_params)

    else:
        model = AutoModelForSequenceClassification.from_pretrained(
        args.model_path, 
        problem_type="multi_label_classification",
        num_labels=len(labels),
        id2label=id2label,
        label2id=label2id
        )
    

    targs = TrainingArguments(
        output_dir=args.output_dir,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.valid_batch_size,
        num_train_epochs=args.epochs,
        weight_decay=args.weight_decay,
        load_best_model_at_end=True,
        metric_for_best_model= "f1",
    )

    
    def multi_label_metrics(predictions, labels, threshold=0.5):
        # first, apply sigmoid on predictions which are of shape (batch_size, num_labels)
        sigmoid = torch.nn.Sigmoid()
        probs = sigmoid(torch.Tensor(predictions))
        # next, use threshold to turn them into integer predictions
        y_pred = np.zeros(probs.shape)
        y_pred[np.where(probs >= threshold)] = 1
        # finally, compute metrics
        y_true = labels

        f1_micro_average = f1_score(y_true=y_true, y_pred=y_pred, average='micro')
        roc_auc = roc_auc_score(y_true, y_pred, average='micro')
        accuracy = accuracy_score(y_true, y_pred)

        tn, fp, fn, tp = confusion_matrix(y_true.ravel(), y_pred.ravel()).ravel()
        sensitivity = tp / (tp + fn)
        specificity = tn / (tn + fp)
        youden_j = sensitivity + specificity - 1

        precision = precision_score(y_true=y_true, y_pred=y_pred, average='micro')

        recall = recall_score(y_true=y_true, y_pred=y_pred, average='micro')

        metrics = {'f1': f1_micro_average,
                   'sensitivity': sensitivity,
                   'specificity': specificity,
                   'roc_auc': roc_auc,
                   'accuracy': accuracy,
                   'youden_j': youden_j,
                   'precision': precision,
                   'recall': recall
                   }
        
        return metrics
        

    def compute_metrics(p: EvalPrediction):
        preds = p.predictions[0] if isinstance(p.predictions, tuple) else p.predictions
        result = multi_label_metrics(predictions=preds, labels=p.label_ids)
        with open(f"{args.output_dir}log.txt", "a") as f:
            f.write(json.dumps(result) + '\n')
        return result
        

    def jsonlload(fname):
        with open(fname, "r", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
            j_list = [json.loads(line) for line in lines]
        return j_list

    
    def jsonldump(j_list, fname):
        with open(fname, "w", encoding='utf-8') as f:
            for json_data in j_list:
                f.write(json.dumps(json_data, ensure_ascii=False)+'\n')

    
    class TestInferenceCallback(TrainerCallback):
        def on_epoch_end(self, args, state, control, model=None, **kwargs):
            logger.info("Epoch ended. Running inference on test set...")
            test_dataset = encoded_test_ds
        
            trainer = Trainer(
                model,
                targs,
                compute_metrics=compute_metrics
            )
        
            predictions, label_ids, _ = trainer.predict(test_dataset)
            sigmoid = torch.nn.Sigmoid()
            threshold_values = sigmoid(torch.Tensor(predictions))
            outputs = (threshold_values >= 0.5).tolist()
        
            j_list = jsonlload("/YBEOBE/data/nikluge-ea-2023-test.jsonl")
            
            for idx, oup in enumerate(outputs):
                j_list[idx]["output"] = {}
            
                # oup에서 True 또는 1인 값의 개수를 확인
                true_count = sum(oup)
            
                if true_count >= 4:
                    # threshold_values의 상위 3개 인덱스를 찾음
                    top_three_indices = np.argsort(threshold_values[idx])[-3:]
                    # oup를 모두 False로 초기화
                    oup = [False] * len(oup)
                    # 상위 3개 인덱스만 True로 설정
                    for top_idx in top_three_indices:
                        oup[top_idx] = True
                    
                elif not any(oup):
                    max_index = threshold_values[idx].argmax().item()
                    oup[max_index] = True

                for jdx, v in enumerate(oup):
                    if v:
                        j_list[idx]["output"][id2label[jdx]] = "True"
                    else:
                        j_list[idx]["output"][id2label[jdx]] = "False"
        
            jsonldump(j_list, os.path.join(args.output_dir, f"test_predictions_epoch_{state.epoch}.jsonl"))
            # torch.save(model.state_dict(), f"{args.output_dir}epoch_{state.epoch}_model_path_pretrained.pth")  # pth 파일로 모델 저장장


    trainer_class = LossFunctionTrainer if args.model_choice == "ASL_loss" else Trainer

    # Trainer 객체 생성
    trainer = trainer_class(
        model,
        targs,
        train_dataset=encoded_tds,
        eval_dataset=encoded_vds,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
        callbacks=[TestInferenceCallback()]
    )
    trainer.train()


if __name__ == "__main__":
    exit(main(parser.parse_args()))
