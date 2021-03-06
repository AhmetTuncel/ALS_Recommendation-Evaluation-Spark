from pyspark import SparkContext
from pyspark.mllib.recommendation import ALS, Rating
from pyspark.sql import HiveContext
from pyspark.mllib.evaluation import RankingMetrics
import os

# pyspark need to enter the following command before you begin to run it:
# export PYSPARK_DRIVER_PYTHON=/usr/bin/python

"""
# For the Spark app
sc = ""
if __name__ == "__main__":
   os.environ['SPARK_HOME'] = "C:\spark"
   sc = SparkContext()
"""

# Using HiveContext, you can create and find tables in the HiveMetaStore and write queries on it using HiveQL.Then createing an object that called SqlContext 

sqlContext = HiveContext(sc)

# Avoid info log level 
sc.setLogLevel("WARN")

# Parameters to be used throughout the program

# In the begining about these parameters set by our self-intuitive.
# To optimal parameters you have to use like grid-search algorithm 

# Baseline params: 100, 3000, 75, 1.0, 40.0

# If a user has bought more than this number, you filter all input data of the user. (for my case this value is 100)
genuine_user_max_product = 100

# If a product taken by singular users you filter all input data (for my case this value 3000)
recommendable_product_max_user = 3000

# We think about how many hidden factors (tastes) are in the model.

als_rank = [75, 100, 150]

# How many iterations in martix factorization
als_iterations = 10

# als_lambda is overfitting (regularization) parameter

als_lambda = [10.0, 1.0, 0.01]

als_alpha = [40.0, 10.0, 1.0, 0.1, 0.01]

num_recommend_item_per_user = 5

raw_data_under_partitioned = sc.textFile("/user/clouderaadmin/hdfs/InternetSalesSources")\
   .map(lambda x: x.split(";"))

partitionCount = 2 * 3 * (8 - 1)
raw_data_unfiltered = raw_data_under_partitioned.repartition(partitionCount)

raw_data = raw_data_unfiltered.filter(
   lambda (user, product, rating): int(user) < 2147483647 and int(product) < 2147483647 and float(rating) > 0.0)

distinct_user_products = raw_data.map(lambda (user, product, rating): (user, 1))

user_product_counts = distinct_user_products.reduceByKey(lambda x, y: x + y)

genuine_users = user_product_counts.filter(lambda (user, num_items): num_items > 1 and num_items < genuine_user_max_product)

raw_data_user_pair_rdd = raw_data.map(lambda (user, product, rating): (user, (product, rating)))

genuine_user_purchases = raw_data_user_pair_rdd.join(genuine_users)

user_cleaned_data = genuine_user_purchases.map(lambda (user, ((product, rating), num_items)): (product, (user, rating)))


distinct_product_users = raw_data.map(lambda (user, product, rating): (product, 1))

product_user_counts = distinct_product_users.reduceByKey(lambda x, y: x + y)

recommendableProducts = product_user_counts.filter(
   lambda (product, num_users): 1 < num_users < recommendable_product_max_user)

   
final_data_raw = user_cleaned_data.join(recommendableProducts)

data = final_data_raw.map(lambda (product, ((user, rating), num_users)): (user, product, rating))


2all_ratings = data.map(lambda (user, item, rating): Rating(int(user), int(item), float(rating)))


splits = all_ratings.randomSplit([0.7, 0.3], 42)
training = splits[0]
test_raw = splits[1]


test = test_raw.map(lambda (user, product, rating): (user, product))\
   .groupByKey()\
   .mapValues(lambda values: list(values))


training.persist()
test.persist()


for (rank, lambda_, alpha) in [(rank, lambda_, alpha) for rank in als_rank for lambda_ in als_lambda for alpha in als_alpha]:


   model = ALS.trainImplicit(ratings=training, rank=rank, iterations=als_iterations, lambda_=lambda_, alpha=alpha)

   table_name = "recs_rank{0}_alpha{1}_lambda{2}".format(str(rank), str(alpha).replace(".", "_"),
                                                         str(lambda_).replace(".", "_"))

   model.save(sc, "/tmp/rec_models/" + table_name)


   raw_predictions = model.recommendProductsForUsers(num_recommend_item_per_user)\
       .flatMap(lambda (user, rankings): rankings)
   raw_predictions.persist()


   raw_predictions_df = sqlContext.createDataFrame(raw_predictions)

   raw_predictions_df.saveAsTable(table_name)


   predictions = raw_predictions \
       .map(lambda (user, product, rankings): (user, product)) \
       .groupByKey() \
       .mapValues(lambda values: list(values))

   predictionAndTruth = predictions.join(test).map(
       lambda (user, (predicted_items, actual_items)): (predicted_items, actual_items))

   metrics = RankingMetrics(predictionAndTruth)


   results = "{0},{1},{2},{3}\n".format(rank, lambda_, alpha,
                                                                    metrics.precisionAt(num_recommend_item_per_user))
   print results
   fo = open("/home/ClouderaLcw/results.txt", "wa")
   fo.write(results)
   fo.close()



