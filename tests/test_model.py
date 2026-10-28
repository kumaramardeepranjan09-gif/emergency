import unittest
from tools.train_model import evaluate, train

class ModelEvaluationTests(unittest.TestCase):
    def test_confusion_metrics_and_tied_auc(self):
        m=evaluate([0,0,1,1],[.1,.9,.2,.9])
        self.assertEqual(m['confusion_matrix'],dict(tn=1,fp=1,fn=1,tp=1))
        self.assertEqual(m['precision'],.5)
        self.assertEqual(m['recall'],.5)
        self.assertEqual(m['f1'],.5)
        self.assertEqual(m['roc_auc'],.625)
    def test_refuses_invalid_grouped_holdout(self):
        with self.assertRaises(ValueError):train([])
        rows=[dict(machine_id=str(i),temp_c=28,vibration_g=.1,rotation_dps=2,used_hours=1,failed_next_hour=0) for i in range(10)]
        with self.assertRaises(ValueError):train(rows)
